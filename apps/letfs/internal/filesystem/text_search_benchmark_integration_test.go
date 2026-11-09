//go:build integration

package filesystem

import (
	"encoding/json"
	"fmt"
	"math/rand/v2"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/stretchr/testify/require"
)

// Opt in: this experiment loads hundreds of MiB and retains raw default-planner evidence.
func TestTextSearchQueryPlans(t *testing.T) {
	out := os.Getenv("OPENLET_TEXT_SEARCH_BENCHMARK_OUTPUT")
	if out == "" {
		t.Skip("set OPENLET_TEXT_SEARCH_BENCHMARK_OUTPUT to run the disposable PostgreSQL experiment")
	}
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	ctx := t.Context()
	var version string
	require.NoError(t, db.QueryRow(ctx, "SELECT version()").Scan(&version))
	report := map[string]any{"version": version, "sql": textCandidatesSQL, "corpora": []any{}}
	t.Cleanup(func() {
		body, err := json.MarshalIndent(report, "", "  ")
		require.NoError(t, err)
		require.NoError(t, os.WriteFile(out, append(body, '\n'), 0o644))
	})
	// No planner hints/settings. Capture server defaults and actual TOAST-aware relation sizes.
	var settings []byte
	require.NoError(t, db.QueryRow(ctx, `SELECT json_object_agg(name,setting) FROM pg_settings WHERE name IN ('shared_buffers','work_mem','random_page_cost','seq_page_cost','effective_cache_size','jit','plan_cache_mode')`).Scan(&settings))
	report["settings"] = json.RawMessage(settings)
	fs, scope, foreign, root, otherRoot, box := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	tx, err := db.Begin(ctx)
	require.NoError(t, err)
	_, err = tx.Exec(ctx, `INSERT INTO filesystems(id,limit_bytes) VALUES($1,1073741824);
`, fs)
	require.NoError(t, err)
	_, err = tx.Exec(ctx, `INSERT INTO scopes(id,filesystem_id,root_id) VALUES($1,$3,$4),($2,$3,$5)`, scope, foreign, fs, root, otherRoot)
	require.NoError(t, err)
	_, err = tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,name,kind) VALUES($1,$3,'home','directory'),($2,$4,'foreign','directory')`, root, otherRoot, scope, foreign)
	require.NoError(t, err)
	_, err = tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,'box','directory')`, box, scope, root)
	require.NoError(t, err)
	require.NoError(t, tx.Commit(ctx))
	anyGIN := false
	for _, corpus := range []struct {
		name        string
		count, size int
		logs        bool
	}{{"docs_8k", 4096, 8192, false}, {"docs_64k", 512, 65536, false}, {"logs_8k", 4096, 8192, true}, {"docs_128m", 16384, 8192, false}} {
		t.Log("loading", corpus.name)
		_, err = db.Exec(ctx, `DROP INDEX IF EXISTS files_text_content_trgm; DELETE FROM nodes WHERE kind='file'`)
		require.NoError(t, err)
		rng := rand.New(rand.NewPCG(20261108, 7))
		nodes, files := make([][]any, 0, corpus.count+128), make([][]any, 0, corpus.count+128)
		words := strings.Fields("workspace agent request message file content context permission scope backend search report calendar temporal checkpoint thông tin dữ liệu")
		for i := range corpus.count + 128 {
			id, parent, owner := uuid.New(), root, scope
			if i < 128 {
				parent = box
			} else if i >= corpus.count {
				parent, owner = otherRoot, foreign
			}
			body := fmt.Sprintf("request file %06d\n", i)
			if i%128 == 0 {
				body += "needleopenlet\n"
			}
			if i == 0 {
				body += "literal %_\\ and Kelvin K\n"
			}
			var b strings.Builder
			b.Grow(corpus.size + 100)
			b.WriteString(body)
			for b.Len() < corpus.size {
				if corpus.logs {
					fmt.Fprintf(&b, "%016x request\n", rng.Uint64())
				} else {
					b.WriteString(words[rng.IntN(len(words))] + " ")
				}
			}
			// Trim at a UTF-8 boundary, then pad so every file has the advertised exact size.
			content := []rune(b.String())
			body = string(content)
			for len(body) > corpus.size {
				content = content[:len(content)-1]
				body = string(content)
			}
			body += strings.Repeat(" ", corpus.size-len(body))
			payload := textPayload([]byte(body))
			nodes = append(nodes, []any{id, owner, parent, fmt.Sprintf("file-%06d.txt", i), "file", len(body)})
			files = append(files, []any{id, "text", "text/plain", body, payload.NewlineCount, payload.SHA256})
		}
		_, err = db.CopyFrom(ctx, pgx.Identifier{"nodes"}, []string{"id", "scope_id", "parent_id", "name", "kind", "size_bytes"}, pgx.CopyFromRows(nodes))
		require.NoError(t, err)
		_, err = db.CopyFrom(ctx, pgx.Identifier{"files"}, []string{"node_id", "storage_kind", "media_type", "text_content", "newline_count", "text_sha256"}, pgx.CopyFromRows(files))
		require.NoError(t, err)
		// A real file-owned artifact participates in traversal and the metadata union.
		source, artifact := uuid.New(), uuid.New()
		_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$3,$4,'report.pdf','file',1),($2,$3,$1,'nested.md','file',14)`, source, artifact, scope, box)
		require.NoError(t, err)
		_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline','x','application/pdf')`, source)
		require.NoError(t, err)
		payload := textPayload([]byte("needleopenlet\n"))
		_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,text_content,newline_count,text_sha256) VALUES($1,'text',$2,$3,$4)`, artifact, payload.Text, payload.NewlineCount, payload.SHA256)
		require.NoError(t, err)
		_, err = db.Exec(ctx, "VACUUM ANALYZE files")
		require.NoError(t, err)
		_, err = db.Exec(ctx, "ANALYZE nodes")
		require.NoError(t, err)
		entry := map[string]any{"name": corpus.name, "rows": corpus.count + 128, "logical_bytes": (corpus.count + 128) * corpus.size}
		report["corpora"] = append(report["corpora"].([]any), entry)
		queries := map[string]any{}
		entry["queries"] = queries
		type measurement struct {
			Samples []float64         `json:"samples_ms"`
			Plans   []json.RawMessage `json:"plans"`
			Median  float64           `json:"median_ms"`
			Rows    int               `json:"returned_rows"`
			Bytes   int               `json:"returned_json_bytes"`
		}
		results := map[string][]byte{}
		measure := func(root uuid.UUID, literal string) measurement {
			t.Helper()
			args := []any{scope, root, literalPattern(literal), MaxTreeEntries + 1, false}
			rows, queryErr := db.Query(ctx, textCandidatesSQL, args...)
			require.NoError(t, queryErr)
			values, queryErr := pgx.CollectRows(rows, func(row pgx.CollectableRow) ([]any, error) { return row.Values() })
			require.NoError(t, queryErr)
			encoded, queryErr := json.Marshal(values)
			require.NoError(t, queryErr)
			key := root.String() + literal
			if before, ok := results[key]; ok {
				require.JSONEq(t, string(before), string(encoded), "index must not alter paths, metadata or ordering")
			} else {
				results[key] = encoded
			}
			if literal == "needleopenlet" {
				want := corpus.count/128 + 2
				if root == box {
					want = 3
				}
				require.Len(t, values, want, "foreign-scope rare matches cannot leak")
			}
			m := measurement{Rows: len(values), Bytes: len(encoded)}
			for i := range 6 {
				var raw []byte
				require.NoError(t, db.QueryRow(ctx, "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) "+textCandidatesSQL, args...).Scan(&raw))
				var plan []struct {
					Execution float64 `json:"Execution Time"`
				}
				require.NoError(t, json.Unmarshal(raw, &plan))
				if i > 0 {
					m.Samples = append(m.Samples, plan[0].Execution)
					m.Plans = append(m.Plans, json.RawMessage(raw))
				}
			}
			sorted := slices.Sorted(slices.Values(m.Samples))
			m.Median = sorted[len(sorted)/2]
			return m
		}
		for _, indexed := range []bool{false, true} {
			label := "before"
			if indexed {
				started := time.Now()
				indexTx, beginErr := db.Begin(ctx)
				require.NoError(t, beginErr)
				_, err = indexTx.Exec(ctx, `SET LOCAL statement_timeout='120s'; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE INDEX files_text_content_trgm ON files USING gin(text_content gin_trgm_ops) WHERE storage_kind='text'`)
				require.NoError(t, err)
				require.NoError(t, indexTx.Commit(ctx))
				entry["index_seconds"] = time.Since(started).Seconds()
				_, err = db.Exec(ctx, "ANALYZE files")
				require.NoError(t, err)
				label = "after"
			}
			for _, q := range []struct{ name, text string }{{"rare", "needleopenlet"}, {"absent", "zzneverpresentzz"}, {"common", "request"}, {"short", "xy"}, {"wildcard", `%_\`}, {"empty", ""}, {"unicode", "K"}} {
				for _, r := range []struct {
					name string
					id   uuid.UUID
				}{{"scope", root}, {"box", box}} {
					key := q.name + "_" + r.name
					if queries[key] == nil {
						queries[key] = map[string]any{}
					}
					m := measure(r.id, q.text)
					queries[key].(map[string]any)[label] = m
					if indexed && q.name == "rare" && r.name == "scope" {
						before := queries[key].(map[string]any)["before"].(measurement)
						gin := strings.Contains(string(m.Plans[0]), "files_text_content_trgm")
						t.Logf("%s rare scope: %.3f -> %.3f ms; default GIN=%v", corpus.name, before.Median, m.Median, gin)
						if gin && slices.Max(m.Samples) < slices.Min(before.Samples) {
							anyGIN = true
						}
					}
				}
			}
			// Same 16-row transactional writer alongside a reader before/after GIN.
			// Rollback keeps the exact corpus identical for all comparisons.
			var writes []float64
			for range 6 {
				writer, beginErr := db.Begin(ctx)
				require.NoError(t, beginErr)
				var wg sync.WaitGroup
				var readErr error
				wg.Go(func() {
					rows, queryErr := db.Query(ctx, textCandidatesSQL, scope, root, literalPattern("needleopenlet"), MaxTreeEntries+1, false)
					if queryErr != nil {
						readErr = queryErr
						return
					}
					_, readErr = pgx.CollectRows(rows, func(row pgx.CollectableRow) ([]any, error) { return row.Values() })
				})
				start := time.Now()
				_, writeErr := writer.Exec(ctx, `UPDATE files SET text_content='X'||substring(text_content FROM 2),text_sha256=encode(sha256(convert_to('X'||substring(text_content FROM 2),'UTF8')),'hex') WHERE node_id=ANY($1)`, func() []uuid.UUID {
					ids := make([]uuid.UUID, 16)
					for i := range ids {
						ids[i] = nodes[i][0].(uuid.UUID)
					}
					return ids
				}())
				writes = append(writes, float64(time.Since(start).Microseconds())/1000)
				rollbackErr := writer.Rollback(ctx)
				wg.Wait()
				require.NoError(t, writeErr)
				require.NoError(t, rollbackErr)
				require.NoError(t, readErr)
			}
			entry["writer_16_rows_rollback_ms_"+label] = writes[1:]
		}
		var sizes, stats []byte
		require.NoError(t, db.QueryRow(ctx, `SELECT json_build_object('heap',pg_relation_size('files'),'table_including_toast',pg_table_size('files'),'gin',pg_relation_size('files_text_content_trgm'),'toast',pg_total_relation_size(reltoastrelid)) FROM pg_class WHERE oid='files'::regclass`).Scan(&sizes))
		require.NoError(t, db.QueryRow(ctx, `SELECT json_agg(row_to_json(s)) FROM (SELECT attname,avg_width,n_distinct,null_frac FROM pg_stats WHERE tablename='files') s`).Scan(&stats))
		entry["sizes"], entry["stats"] = json.RawMessage(sizes), json.RawMessage(stats)
	}
	report["selective_default_gin_gate"] = anyGIN
	require.True(t, anyGIN, "a selective production query must choose GIN and improve beyond sample variance")
}
