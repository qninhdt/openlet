//go:build integration

package testfixture

import (
	"context"
	"crypto/md5"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestSQLBenchmarkProbePreservesFixture(t *testing.T) {
	db := Postgres(t, filepath.Join(sqlBenchmarkRoot, "apps/letfs/migrations/0001_initial.sql"))
	conn, err := db.Acquire(t.Context())
	require.NoError(t, err)
	defer conn.Release()
	ctx := context.WithValue(t.Context(), sqlProbeKey{}, true)
	_, err = conn.Exec(ctx, `CREATE TEMP TABLE sql_benchmark_guard(id int PRIMARY KEY,value text)`)
	require.NoError(t, err)
	b := sqlBenchmark{t: t}
	plans, err := b.probe(ctx, conn.Conn(), `INSERT INTO sql_benchmark_guard VALUES($1,$2) RETURNING id`, []any{1, "original"})
	require.NoError(t, err)
	require.Len(t, plans, 4)
	require.Equal(t, float64(1), sqlWorkRows(plans[3].Plan))
	var count int
	require.NoError(t, conn.QueryRow(ctx, `SELECT count(*) FROM sql_benchmark_guard`).Scan(&count))
	require.Zero(t, count)
	require.Equal(t, byte('I'), conn.Conn().PgConn().TxStatus())
	_, err = conn.Exec(ctx, `INSERT INTO sql_benchmark_guard VALUES(1,'original')`)
	require.NoError(t, err)
	for _, c := range []struct {
		query string
		rows  float64
	}{
		{`INSERT INTO sql_benchmark_guard VALUES(1,'changed') ON CONFLICT(id) DO UPDATE SET value=excluded.value`, 1},
		{`INSERT INTO sql_benchmark_guard VALUES(1,'changed') ON CONFLICT(id) DO UPDATE SET value=excluded.value WHERE false`, 0},
		{`INSERT INTO sql_benchmark_guard VALUES(1,'changed') ON CONFLICT DO NOTHING`, 0},
	} {
		plans, err := b.probe(ctx, conn.Conn(), c.query, nil)
		require.NoError(t, err)
		require.Equal(t, c.rows, sqlWorkRows(plans[3].Plan))
	}
	_, err = conn.Exec(ctx, `BEGIN`)
	require.NoError(t, err)
	_, err = conn.Exec(ctx, `INSERT INTO sql_benchmark_guard VALUES(2,'parent transaction')`)
	require.NoError(t, err)
	for _, query := range []string{`UPDATE sql_benchmark_guard SET value='changed' WHERE id=$1 RETURNING id`, `DELETE FROM sql_benchmark_guard WHERE id=$1 RETURNING id`} {
		_, err = b.probe(ctx, conn.Conn(), query, []any{1})
		require.NoError(t, err)
		var value string
		require.NoError(t, conn.QueryRow(ctx, `SELECT value FROM sql_benchmark_guard WHERE id=1`).Scan(&value))
		require.Equal(t, "original", value)
		require.NoError(t, conn.QueryRow(ctx, `SELECT count(*) FROM sql_benchmark_guard`).Scan(&count))
		require.Equal(t, 2, count)
	}
	_, err = b.probe(ctx, conn.Conn(), `INSERT INTO sql_benchmark_guard VALUES($1,$2)`, []any{1, "duplicate"})
	require.Equal(t, "23505", sqlErrorCode(err))
	require.Equal(t, byte('T'), conn.Conn().PgConn().TxStatus())
	_, err = conn.Exec(ctx, `ROLLBACK`)
	require.NoError(t, err)
}

func TestSQLBenchmarkAdditionalQueries(t *testing.T) {
	for _, service := range []string{"account", "workspace", "letfs"} {
		t.Run(service, func(t *testing.T) {
			db := Postgres(t, filepath.Join(sqlBenchmarkRoot, "apps", service, "migrations/0001_initial.sql"))
			conn, err := db.Acquire(t.Context())
			require.NoError(t, err)
			defer conn.Release()
			ctx := context.WithValue(t.Context(), sqlProbeKey{}, true)
			id := uuid.MustParse("11111111-1111-4111-8111-111111111111")
			scope := uuid.MustParse("22222222-2222-4222-8222-222222222222")
			fixtureID := func(label string) uuid.UUID { return uuid.UUID(md5.Sum([]byte(label))) }
			seed := `INSERT INTO accounts(id,type,clerk_id) SELECT md5('account-'||i)::uuid,'user','clerk-'||i FROM generate_series(1,100000) i;`
			if service == "workspace" {
				seed = fmt.Sprintf(`
INSERT INTO workspaces(id,name,filesystem_id,shared_scope_id) SELECT md5('ws-'||i)::uuid,'workspace',md5('fs-'||i)::uuid,md5('scope-'||i)::uuid FROM generate_series(1,10000) i;
INSERT INTO workspaces(id,name,filesystem_id,shared_scope_id) VALUES('%s','target',md5('target-fs')::uuid,'%s');
INSERT INTO workspace_members(workspace_id,account_id,role,personal_scope_id) SELECT md5('ws-'||((i-1)/10+1))::uuid,md5('member-'||i)::uuid,'member',md5('personal-'||i)::uuid FROM generate_series(1,100000) i;
INSERT INTO workspace_members(workspace_id,account_id,role,personal_scope_id) SELECT '%s',md5('target-member-'||i)::uuid,'member',md5('target-personal-'||i)::uuid FROM generate_series(1,100) i;
INSERT INTO workspace_invitations(id,workspace_id,email,role,token_hash,expires_at) SELECT md5('invite-'||i)::uuid,CASE WHEN i<=100 THEN '%s'::uuid ELSE md5('ws-'||(1+i%%10000))::uuid END,'test-'||i||'@example.test','member',decode(md5(i::text)||md5(i::text),'hex'),now()+interval '1 hour' FROM generate_series(1,10000) i;
INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id,expires_at) SELECT md5('actor-'||i)::uuid,md5('key-'||i)::uuid,'hash',md5('ws-'||(1+i%%10000))::uuid,now()+CASE WHEN i<=100 THEN interval '-1 hour' ELSE interval '1 hour' END FROM generate_series(1,10000) i;`, id, scope, id, id)
				seed += fmt.Sprintf(`INSERT INTO workspace_invitations(id,workspace_id,email,role,token_hash,expires_at) VALUES(md5('expired-invite')::uuid,'%s','expired@example.test','member',decode(md5('expired')||md5('expired'),'hex'),now()-interval '1 hour');`, id)
			}
			if service == "letfs" {
				seed = fmt.Sprintf(`BEGIN;
INSERT INTO filesystems(id,limit_bytes,node_count) VALUES('%[1]s',100000000,100002),(md5('deleting-fs')::uuid,0,0);
UPDATE filesystems SET state='deleting' WHERE id=md5('deleting-fs')::uuid;
INSERT INTO scopes(id,filesystem_id,root_id) VALUES('%[2]s','%[1]s','%[3]s');
INSERT INTO scopes(id,filesystem_id,state) VALUES(md5('deleting-scope')::uuid,'%[1]s','deleting');
INSERT INTO nodes(id,scope_id,name,kind) VALUES('%[3]s','%[2]s','root','directory');
INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) SELECT md5('file-'||i)::uuid,'%[2]s','%[3]s','file-'||i,'file',1 FROM generate_series(1,100000) i;
INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES(md5('derived')::uuid,'%[2]s',md5('file-1')::uuid,'output','file',1);
INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status) SELECT id,'inline','x'::bytea,1,'text','pending' FROM nodes WHERE kind='file';
UPDATE files SET storage_kind='object',inline_bytes=NULL,object_key='fixture/object-2' WHERE node_id=md5('file-2')::uuid;
UPDATE files SET storage_kind='object',inline_bytes=NULL,object_key='fixture/object-4' WHERE node_id=md5('file-4')::uuid;
UPDATE nodes SET parent_id=NULL WHERE id=md5('file-3')::uuid;
INSERT INTO trash_entries(id,scope_id,node_id,original_parent_id,original_name,actor_id) VALUES(md5('trash')::uuid,'%[2]s',md5('file-3')::uuid,md5('file-1')::uuid,'original-name',md5('actor')::uuid);
INSERT INTO uploads(id,scope_id,input,transport,candidate_key,expected_size,content_md5,processing_file_id,processing_generation,relative_path,processing_stage) SELECT md5('upload-'||i)::uuid,'%[2]s','{}','single','candidate-'||i,1,'CY9rzUYh03PK3k6DJie09g==',md5('file-'||i)::uuid,1,'output','parse' FROM generate_series(1,100000) i;
INSERT INTO uploads(id,scope_id,actor_id,input,transport,candidate_key,expected_size,part_size) VALUES(md5('multipart')::uuid,'%[2]s',md5('actor')::uuid,'{}','multipart','multipart-candidate',1,5242880);
INSERT INTO object_deletions(object_key,filesystem_id) VALUES('fixture/object-2','%[1]s');
INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) SELECT 'actor/'||i,'process-file',i::text,'hash',jsonb_build_object('file_id',md5('file-'||i)::uuid,'generation',1) FROM generate_series(1,100000) i;
INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result,expires_at) SELECT 'expired/'||i,'create-node',i::text,'hash','{}',now()-interval '1 hour' FROM generate_series(1,100) i;
INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result,expires_at) VALUES('fixture/actor','create-upload','upload','hash',jsonb_build_object('id',md5('upload-1')::uuid),NULL),('fixture/actor','create-node','node','hash','{}',NULL),('fixture/actor','copy-node','copy','hash','{}',now()+interval '1 hour');
COMMIT;`, id, scope, fixtureID("root"))
			}
			_, err = conn.Exec(ctx, seed+" ANALYZE;")
			require.NoError(t, err)
			b := db.Config().ConnConfig.Tracer.(*sqlBenchmark)
			cases := []struct {
				file string
				line int
				args []any
			}{
				{"account/service.go", 38, []any{"clerk-50000"}},
				{"workspace/invitations.go", 87, []any{id, uuid.Nil, 51}},
				{"workspace/invitations.go", 115, []any{uuid.Nil, id}},
				{"workspace/maintenance.go", 6, nil},
				{"workspace/relations.go", 171, []any{id, scope}},
				{"workspace/service.go", 244, []any{id}},
				{"workspace/store.go", 175, []any{id, uuid.Nil, 51}},
				{"workspace/deletion.go", 50, []any{id}},
				{"workspace/invitations.go", 57, []any{id, "expired@example.test"}},
				{"workspace/invitations.go", 60, []any{id, "test-1@example.test"}},
			}
			if service == "letfs" {
				file, object, upload, root := fixtureID("file-1"), fixtureID("file-2"), fixtureID("upload-1"), fixtureID("root")
				cases = []struct {
					file string
					line int
					args []any
				}{
					{"filesystem/artifacts.go", 120, []any{file, int64(1), id}},
					{"filesystem/artifacts.go", 129, []any{file, int64(1)}},
					{"filesystem/artifacts.go", 135, []any{file.String(), "1"}},
					{"filesystem/artifacts.go", 167, []any{file, scope}},
					{"filesystem/copy.go", 126, []any{"fixture/actor", "copy"}},
					{"filesystem/copy_data.go", 96, []any{"fixture/object-2"}},
					{"filesystem/deletion.go", 123, []any{[]uuid.UUID{object}, id, scope}},
					{"filesystem/deletion.go", 131, []any{scope, []uuid.UUID{file}}},
					{"filesystem/download.go", 46, []any{object}},
					{"filesystem/node_writes.go", 176, []any{"fixture/actor", "node"}},
					{"filesystem/provisioning.go", 228, nil},
					{"filesystem/scope_move.go", 106, []any{file}},
					{"filesystem/trash.go", 29, []any{fixtureID("file-4"), id}},
					{"filesystem/upload_publication.go", 210, []any{object, int64(2)}},
					{"filesystem/upload_publication.go", 216, []any{fixtureID("new-node"), scope, root, "new-file", int64(1)}},
					{"filesystem/upload_publication.go", 227, []any{object, "fixture/new-object", "text/plain"}},
					{"filesystem/upload_publication.go", 247, []any{upload, object, []byte(`{"id":"fixture"}`)}},
					{"filesystem/upload_publication.go", 255, []any{upload.String()}},
					{"filesystem/upload_publication.go", 287, []any{upload}},
					{"filesystem/uploads.go", 174, []any{scope, root, "file-1"}},
					{"filesystem/uploads.go", 244, []any{"fixture/actor", "upload"}},
					{"filesystem/uploads.go", 295, []any{fixtureID("new-upload"), scope, fixtureID("actor"), []byte(`{}`), "fixture/new-candidate", "single", int64(1), "CY9rzUYh03PK3k6DJie09g==", nil}},
					{"filesystem/uploads.go", 305, []any{"fixture/actor", "new-upload", "hash", []byte(`{}`)}},
					{"filesystem/uploads.go", 366, []any{upload, time.Now().Add(time.Hour)}},
					{"filesystem/uploads.go", 432, []any{fixtureID("multipart"), "fixture-multipart-id"}},
					{"temporal/maintenance.go", 68, nil},
					{"temporal/maintenance.go", 81, nil},
				}
			}
			// Use a seeded invitation rather than measuring a nonmatching update.
			if service == "workspace" {
				var invite uuid.UUID
				require.NoError(t, conn.QueryRow(ctx, `SELECT id FROM workspace_invitations WHERE email='test-1@example.test'`).Scan(&invite))
				cases[2].args[0] = invite
			}
			for _, c := range cases {
				if service != "letfs" && !strings.HasPrefix(c.file, service+"/") {
					continue
				}
				file := "apps/" + service + "/internal/" + c.file
				var site sqlSite
				for _, candidate := range sqlMeasured.sites {
					if candidate.File == file && candidate.Line == c.line {
						site = candidate
						break
					}
				}
				require.NotEmpty(t, site.File, "inventory site %s:%d", file, c.line)
				query, err := strconv.Unquote(site.Expression)
				require.NoError(t, err, "additional cases must use verbatim literal SQL")
				plans, err := b.probe(ctx, conn.Conn(), query, c.args)
				require.NoError(t, err, "%s:%d", file, c.line)
				r := newSQLMeasurement(site, t.Name(), query, "supplemental_explain_analyze", c.args, plans)
				require.Positive(t, r.WorkRows, "%s:%d must match data", file, c.line)
				b.record(r)
			}
		})
	}
}
