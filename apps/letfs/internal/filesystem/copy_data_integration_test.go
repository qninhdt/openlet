//go:build integration

package filesystem

import (
	"bytes"
	"crypto/md5"
	"encoding/base64"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationCopyPublicationReconcilesRetriesAndRetainsPartialEffects(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	endpoint := testfixture.S3(t)
	target, err := url.Parse(endpoint)
	require.NoError(t, err)
	var drop atomic.Bool
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorLog = log.New(io.Discard, "", 0)
	proxy.ModifyResponse = func(response *http.Response) error {
		if response.Request.Header.Get("X-Amz-Copy-Source") != "" && response.StatusCode == http.StatusOK && drop.Swap(false) {
			_, err := io.Copy(io.Discard, response.Body)
			if err != nil {
				return err
			}
			_ = response.Body.Close()
			return errors.New("test dropped copy response")
		}
		return nil
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, _ error) {
		connection, _, err := w.(http.Hijacker).Hijack()
		if err == nil {
			_ = connection.Close()
		}
	}
	control := httptest.NewServer(proxy)
	defer control.Close()
	objects, err := storage.New(storage.Config{Endpoint: control.URL, SigningEndpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	s := Store{DB: db, Graph: graph, Storage: objects, MaxNodes: 200, MaxCopyNodes: 64, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 20, MaxCleanupBacklog: 20}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, &s, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	root := *created.RootID

	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeReadMetadata, authz.ScopeWrite, authz.ScopeWrite, authz.ScopeTrash, authz.ScopePurge)
	create := func(parent uuid.UUID, name string, data []byte) Node {
		t.Helper()
		input := CreateNode{Parent: Locator{NodeID: &parent}, Name: name}
		if data != nil {
			input.File = &InlineFile{Content: data, MediaType: "application/octet-stream"}
		}
		node, err := s.CreateNode(ctx, fs, uuid.New(), input)
		require.NoError(t, err)
		return node
	}
	admit := func(source Node, name string) copyPlan {
		t.Helper()
		admission, err := s.prepareCopy(ctx, fs, uuid.New(), CreateCopy{DestinationScopeID: fs, SourceID: source.ID, ParentID: root, Name: name, Revision: &source.Revision})
		require.NoError(t, err)
		return admission
	}
	usage := func() int64 {
		t.Helper()
		var used int64
		require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&used))
		return used
	}
	dir := create(root, "source", nil)
	first := create(dir.ID, "first.txt", []byte("first"))
	_ = create(dir.ID, "second.txt", []byte{})
	dir, err = s.GetNode(ctx, fs, Locator{NodeID: &dir.ID})
	require.NoError(t, err)
	tree := admit(dir, "tree-copy")
	require.NoError(t, s.commitCopyItem(ctx, tree, tree.Root))
	frame := copyFrame{SourceScopeID: fs, Item: tree.Root, Revision: 1}
	late := create(dir.ID, "late.txt", []byte("late"))
	copied := 0
	for {
		item, err := s.nextCopyItem(ctx, tree, frame)
		require.NoError(t, err)
		if item == nil {
			break
		}
		require.NotEqual(t, late.ID, item.Source, "captured upper bound excludes later children")
		require.NoError(t, s.commitCopyItem(ctx, tree, *item))
		require.NoError(t, s.commitCopyItem(ctx, tree, *item), "lost commit acknowledgment must not recharge")
		require.NoError(t, s.finishCopyFile(ctx, tree, copyFrame{SourceScopeID: fs, Item: *item, Revision: 1}))
		require.NoError(t, s.finishCopyFile(ctx, tree, copyFrame{SourceScopeID: fs, Item: *item, Revision: 1}))
		frame.After = item.Source
		frame.Revision++
		copied++
	}
	require.Equal(t, 2, copied)
	require.EqualValues(t, 14, usage(), "two originals, late child and one exact copy")
	var generation int64
	require.NoError(t, db.QueryRow(ctx, `SELECT desired_generation FROM files WHERE node_id=$1`, copyDestination(tree.ID, first.ID)).Scan(&generation))
	require.EqualValues(t, 1, generation)

	// Source content changes after a committed write cannot make its retry charge again.
	source := create(root, "replay.txt", []byte("old"))
	replay := admit(source, "replay-copy.txt")
	before := usage()
	require.NoError(t, s.commitCopyItem(ctx, replay, replay.Root))
	_, err = s.ReplaceContent(ctx, fs, Locator{NodeID: &source.ID}, &source.Revision, []byte("new"), "text/plain")
	require.NoError(t, err)
	require.NoError(t, s.commitCopyItem(ctx, replay, replay.Root))
	require.Equal(t, before+3, usage())
	destination, err := s.GetNode(ctx, fs, Locator{NodeID: &replay.Root.Destination})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, fs, Locator{NodeID: &destination.ID}, &destination.Revision)
	require.NoError(t, err)
	_, err = s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.NoError(t, err)
	done, err := s.DeletionBatch(ctx, fs, &entry.ID)
	require.NoError(t, err)
	require.True(t, done)

	// Derived forests preserve provenance and initialize one logical processing generation.
	document := create(root, "source.pdf", []byte("document"))
	artifacts := create(root, "artifact-stage", nil)
	output := create(artifacts.ID, "README.md", []byte("derived"))
	_, err = db.Exec(ctx, `UPDATE nodes SET parent_id=$2,name='pages' WHERE id=$1`, artifacts.ID, document.ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE nodes SET revision=revision+1 WHERE id=$1`, document.ID)
	require.NoError(t, err)
	document, err = s.GetNode(ctx, fs, Locator{NodeID: &document.ID})
	require.NoError(t, err)
	derived := admit(document, "copied.pdf")
	var walk func(copyItem)
	walk = func(item copyItem) {
		t.Helper()
		require.NoError(t, s.commitCopyItem(ctx, derived, item))
		frame := copyFrame{SourceScopeID: fs, Item: item, Revision: 1}
		for {
			child, err := s.nextCopyItem(ctx, derived, frame)
			require.NoError(t, err)
			if child == nil {
				break
			}
			walk(*child)
			frame.After = child.Source
			frame.Revision++
		}
		require.NoError(t, s.finishCopyFile(ctx, derived, frame))
	}
	walk(derived.Root)
	copiedOutput := copyDestination(derived.ID, output.ID)
	_, err = s.ReplaceContent(ctx, fs, Locator{NodeID: &copiedOutput}, ptr(int64(1)), []byte("invalid"), "text/plain")
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(err))
	var publication string
	require.NoError(t, db.QueryRow(ctx, `SELECT publication_status,desired_generation FROM files WHERE node_id=$1`, derived.Root.Destination).Scan(&publication, &generation))
	require.Equal(t, "parsed", publication)
	require.EqualValues(t, 1, generation)

	// Ambiguous object writes stay counted through a successful retry.
	payload := []byte{0, 255, 1, 2}
	remote := create(root, "remote.bin", payload)
	key := "source/" + remote.ID.String()
	digest := md5.Sum(payload)
	capability, err := objects.SignPut(ctx, key, int64(len(payload)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
	require.NoError(t, err)
	request, err := http.NewRequestWithContext(ctx, http.MethodPut, capability.URL, bytes.NewReader(payload))
	require.NoError(t, err)
	for name, value := range capability.Headers {
		request.Header.Set(name, value)
	}
	response, err := (&http.Client{Timeout: 10 * time.Second}).Do(request)
	require.NoError(t, err)
	require.Equal(t, http.StatusOK, response.StatusCode)
	require.NoError(t, response.Body.Close())
	_, err = db.Exec(ctx, `UPDATE files SET storage_kind='object',inline_bytes=NULL,object_key=$2 WHERE node_id=$1`, remote.ID, key)
	require.NoError(t, err)
	objectCopy := admit(remote, "remote-copy.bin")
	before = usage()
	drop.Store(true)
	err = s.commitCopyItem(ctx, objectCopy, objectCopy.Root)
	require.Equal(t, "DEPENDENCY_UNAVAILABLE", reason(err))
	require.Equal(t, before, usage())
	candidate := "objects/" + filesystemID.String() + "/" + objectCopy.Root.Destination.String()
	var writes int64
	require.NoError(t, db.QueryRow(ctx, `SELECT open_writes FROM object_deletions WHERE object_key=$1`, candidate).Scan(&writes))
	require.EqualValues(t, 1, writes)
	require.NoError(t, s.commitCopyItem(ctx, objectCopy, objectCopy.Root))
	require.NoError(t, s.commitCopyItem(ctx, objectCopy, objectCopy.Root))
	require.Equal(t, before+4, usage())
	require.NoError(t, db.QueryRow(ctx, `SELECT open_writes FROM object_deletions WHERE object_key=$1`, candidate).Scan(&writes))
	require.EqualValues(t, 1, writes, "unknown first request cannot be forgotten")
	reader, err := objects.Open(ctx, candidate)
	require.NoError(t, err)
	data, err := io.ReadAll(reader)
	require.NoError(t, reader.Close())
	require.NoError(t, err)
	require.Equal(t, payload, data)

	// Publication rejection closes the known write while preserving cleanup evidence.
	failed := admit(remote, "over-quota.bin")
	before = usage()
	_, err = db.Exec(ctx, `UPDATE filesystems SET limit_bytes=used_bytes WHERE id=$1`, filesystemID)
	require.NoError(t, err)
	err = s.commitCopyItem(ctx, failed, failed.Root)
	require.Equal(t, "QUOTA_EXCEEDED", reason(err))
	require.Equal(t, before, usage())
	candidate = strings.Replace(candidate, objectCopy.Root.Destination.String(), failed.Root.Destination.String(), 1)
	require.NoError(t, db.QueryRow(ctx, `SELECT open_writes FROM object_deletions WHERE object_key=$1`, candidate).Scan(&writes))
	require.Zero(t, writes)
	var exists bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE id=$1)`, failed.Root.Destination).Scan(&exists))
	require.False(t, exists)
	_, err = db.Exec(ctx, `UPDATE object_deletions SET state='deleting' WHERE object_key=$1`, candidate)
	require.NoError(t, err)
	err = s.commitCopyItem(ctx, failed, failed.Root)
	require.Equal(t, "COPY_CANDIDATE_CLOSED", reason(err))
}
