package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/config"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/status"
)

func main() {
	schema := flag.String("schema", "/contracts/schema.zed", "expected authorization schema")
	roles := flag.String("roles", "/contracts/roles.json", "expected built-in role capabilities")
	check := flag.Bool("check", false, "verify schema and role policy without changing them")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, *schema, *roles, *check); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println("Authorization schema and role policy verified.")
}

func run(ctx context.Context, path, rolesPath string, check bool) error {
	plaintext := config.Secret("ALLOW_PLAINTEXT_RPC")
	if plaintext != "" && plaintext != "false" && plaintext != "true" {
		return errors.New("ALLOW_PLAINTEXT_RPC must be true or false")
	}
	schema, err := os.ReadFile(path)
	if err != nil {
		return errors.New("expected authorization schema file is unavailable")
	}
	roles, err := os.ReadFile(rolesPath)
	if err != nil {
		return errors.New("expected authorization role policy file is unavailable")
	}
	policy, err := authz.ParseRolePolicy(roles)
	if err != nil {
		return err
	}
	connection, err := rpc.Dial(config.Secret("SPICEDB_ADDRESS"), config.Secret("SPICEDB_GRPC_PRESHARED_KEY"), rpc.Transport{AllowPlaintext: plaintext == "true"})
	if err != nil {
		return errors.New("authorization transport configuration rejected")
	}
	defer connection.Close()
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	client := v1.NewSchemaServiceClient(connection)
	if check {
		err = authz.VerifySchema(ctx, client, string(schema))
	} else {
		err = authz.InitializeSchema(ctx, client, string(schema))
	}
	if errors.Is(err, authz.ErrSchemaMismatch) {
		return authz.ErrSchemaMismatch
	}
	if err != nil {
		return fmt.Errorf("authorization schema operation failed (%s)", status.Code(err))
	}
	graph := v1.NewPermissionsServiceClient(connection)
	if check {
		err = authz.VerifyRolePolicy(ctx, graph, policy)
	} else {
		err = authz.InitializeRolePolicy(ctx, graph, policy)
	}
	if errors.Is(err, authz.ErrPolicyMismatch) || errors.Is(err, authz.ErrInvalidPolicy) {
		return err
	}
	if err != nil {
		return fmt.Errorf("authorization role policy operation failed (%s)", status.Code(err))
	}
	return nil
}
