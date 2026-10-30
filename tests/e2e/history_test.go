package e2e

import (
	"context"
	"go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	temporalclient "go.temporal.io/sdk/client"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func saveHistory(t *testing.T, id, kind string) {
	t.Helper()
	directory := os.Getenv("OPENLET_HISTORY_DIR")
	if directory == "" {
		return
	}
	tc, e := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if e != nil {
		t.Fatal(e)
	}
	defer tc.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 15*time.Second)
	defer cancel()
	// Wait for the native workflow close event, after its final DB activity commits.
	_ = tc.GetWorkflow(ctx, id, "").Get(ctx, nil)
	iterator := tc.GetWorkflowHistory(ctx, id, "", false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	history := &historypb.History{}
	for iterator.HasNext() {
		event, e := iterator.Next()
		if e != nil {
			t.Fatal(e)
		}
		history.Events = append(history.Events, event)
	}
	if len(history.Events) < 3 {
		t.Fatal("incomplete workflow history", kind)
	}
	data, e := protojson.Marshal(history)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.MkdirAll(directory, 0700); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(directory, kind+".json"), data, 0600); e != nil {
		t.Fatal(e)
	}
	wire, e := proto.Marshal(history)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(directory, kind+".bin"), wire, 0600); e != nil {
		t.Fatal(e)
	}
}

func directoryEnabled() bool { return os.Getenv("OPENLET_HISTORY_DIR") != "" }

func filesystemForNode(t *testing.T, node string) string {
	t.Helper()
	db := serviceDB(t, "letfs")
	var fs string
	if e := db.QueryRow(t.Context(), "SELECT filesystem_id::text FROM nodes WHERE id=$1", node).Scan(&fs); e != nil {
		t.Fatal(e)
	}
	return fs
}
