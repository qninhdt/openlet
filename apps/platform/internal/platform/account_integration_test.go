//go:build integration

package platform

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"buf.build/go/protovalidate"
	clerk "github.com/clerk/clerk-sdk-go/v2"
	"github.com/clerk/clerk-sdk-go/v2/user"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/emptypb"
)

func TestAccountSQL(t *testing.T) {
	ctx := context.Background()
	dsn := os.Getenv("OPENLET_TEST_PLATFORM_DSN")
	if dsn == "" {
		t.Skip("set OPENLET_TEST_PLATFORM_DSN to a disposable PostgreSQL database")
	}
	admin, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	schema := "account_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, err = admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	defer admin.Exec(ctx, "DROP SCHEMA "+schema+" CASCADE")
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal(err)
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema
	db, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	migrations, err := filepath.Glob("../../migrations/*.sql")
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range migrations {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec(ctx, strings.Split(string(data), "-- +goose Down")[0]); err != nil {
			t.Fatal(err)
		}
	}
	own, other := uuid.NewString(), uuid.NewString()
	if _, err = db.Exec(ctx, `INSERT INTO users(id,clerk_subject,display_name) VALUES($1,'own','Before'),($2,'other','Other')`, own, other); err != nil {
		t.Fatal(err)
	}
	s := &Server{DB: db}
	ctx = metadata.NewIncomingContext(ctx, metadata.Pairs("x-openlet-clerk-subject", "own"))
	patch := &pb.UpdateMeRequest{DisplayName: proto.String("  Linh  "), Appearance: &pb.AvatarAppearance{Shape: "nuage", Color: "bleu"}, Preferences: &pb.AccountPreferences{Theme: proto.String("dark"), MessageSound: proto.Bool(true)}}
	if err = protovalidate.Validate(patch); err != nil {
		t.Fatal(err)
	}
	saved, err := s.UpdateMe(ctx, patch)
	if err != nil || saved.DisplayName != "Linh" || saved.Appearance.Shape != "nuage" {
		t.Fatalf("profile save: %v %v", saved, err)
	}
	patch = &pb.UpdateMeRequest{Preferences: &pb.AccountPreferences{MessageSound: proto.Bool(false)}}
	if err = protovalidate.Validate(patch); err != nil {
		t.Fatal(err)
	}
	saved, err = s.UpdateMe(ctx, patch)
	if err != nil || saved.Preferences.GetTheme() != "dark" || saved.Preferences.GetMessageSound() {
		t.Fatalf("settings patch lost another field: %v %v", saved, err)
	}
	reloaded, err := s.GetMe(ctx, &emptypb.Empty{})
	if err != nil || !proto.Equal(saved, reloaded) {
		t.Fatalf("profile did not persist: %v %v", reloaded, err)
	}
	for _, enabled := range []bool{true, false} {
		patch = &pb.UpdateMeRequest{Preferences: &pb.AccountPreferences{ShowAgentSteps: proto.Bool(enabled), CompactMessageActions: proto.Bool(enabled), MessageSound: proto.Bool(enabled)}}
		saved, err = s.UpdateMe(ctx, patch)
		if err != nil {
			t.Fatal(err)
		}
		reloaded, err = s.GetMe(ctx, &emptypb.Empty{})
		if err != nil || !proto.Equal(saved, reloaded) || reloaded.Preferences.GetShowAgentSteps() != enabled || reloaded.Preferences.GetCompactMessageActions() != enabled || reloaded.Preferences.GetMessageSound() != enabled || reloaded.Preferences.GetTheme() != "dark" {
			t.Fatalf("toggle %v did not persist: %v %v", enabled, reloaded, err)
		}
	}
	users, err := s.BatchGetUsers(ctx, &pb.BatchGetUsersRequest{UserIds: []string{own, other}})
	if err != nil {
		t.Fatal(err)
	}
	for _, user := range users.Users {
		if user.Preferences != nil {
			t.Fatal("member response exposed account settings")
		}
	}
	if err = protovalidate.Validate(&pb.UpdateMeRequest{Appearance: &pb.AvatarAppearance{Shape: "invalid", Color: "bleu"}}); err == nil {
		t.Fatal("invalid avatar admitted")
	}
	if err = protovalidate.Validate(&pb.UpdateMeRequest{Preferences: &pb.AccountPreferences{Theme: proto.String("invalid")}}); err == nil {
		t.Fatal("invalid theme admitted")
	}
	if _, err = s.UpdateMe(ctx, &pb.UpdateMeRequest{DisplayName: proto.String("   ")}); err == nil {
		t.Fatal("blank name admitted")
	}
	otherCtx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("x-openlet-clerk-subject", "other"))
	untouched, err := s.GetMe(otherCtx, &emptypb.Empty{})
	if err != nil || untouched.DisplayName != "Other" || untouched.Appearance != nil {
		t.Fatalf("updated another account: %v %v", untouched, err)
	}
	for _, key := range []string{"", "openlet_production_user_id"} {
		t.Run("onboarding metadata "+key, func(t *testing.T) {
			expected := key
			if expected == "" {
				expected = "openlet_user_id"
			}
			updates := 0
			clerkAPI := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				if r.Method == http.MethodGet && r.URL.Path == "/users/own" {
					_, _ = w.Write([]byte(`{"id":"own","first_name":"External profile"}`))
					return
				}
				if r.Method != http.MethodPatch || r.URL.Path != "/users/own/metadata" {
					t.Errorf("unexpected Clerk request: %s %s", r.Method, r.URL.Path)
					w.WriteHeader(http.StatusNotFound)
					return
				}
				var body struct {
					PublicMetadata map[string]string `json:"public_metadata"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
				}
				if len(body.PublicMetadata) != 1 || body.PublicMetadata[expected] != own {
					t.Errorf("onboarding changed another deployment's identity: %v", body.PublicMetadata)
				}
				updates++
				_, _ = w.Write([]byte(`{"id":"own"}`))
			}))
			defer clerkAPI.Close()
			secret := "clerk-test-placeholder"
			s.Clerk = user.NewClient(&clerk.ClientConfig{BackendConfig: clerk.BackendConfig{URL: &clerkAPI.URL, Key: &secret}})
			s.UserIDMetadataKey = key
			for range 2 {
				onboarded, err := s.Onboard(ctx, &emptypb.Empty{})
				if err != nil || onboarded.Id != own || onboarded.DisplayName != saved.DisplayName {
					t.Fatalf("onboarding replaced the existing identity/profile: %v %v", onboarded, err)
				}
			}
			if updates != 2 {
				t.Fatalf("expected two scoped metadata updates, got %d", updates)
			}
		})
	}
}
