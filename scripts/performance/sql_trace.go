//go:build integration

// This file is injected into testfixture by the benchmark's Go overlay only.
package testfixture

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type sqlSite struct {
	File       string `json:"file"`
	Line       int    `json:"line"`
	EndLine    int    `json:"end_line"`
	Function   string `json:"function"`
	Expression string `json:"sql_expression"`
}
type sqlAttempt struct {
	busy, matched bool
	count         int
}

var sqlMeasured = struct {
	sync.Mutex
	sites []sqlSite
	seen  map[string]*sqlAttempt
}{seen: map[string]*sqlAttempt{}}

type sqlBenchmark struct {
	t         *testing.T
	root, out string
}
type sqlTraceKey struct{}
type sqlProbeKey struct{}
type sqlCall struct {
	site    sqlSite
	query   string
	start   time.Time
	control bool
}
type sqlMeasurement struct {
	Site           sqlSite         `json:"site"`
	Test           string          `json:"test"`
	SQL            string          `json:"sql"`
	ParameterTypes []string        `json:"parameter_types,omitempty"`
	ParameterSizes []int           `json:"parameter_sizes,omitempty"`
	Runs           []float64       `json:"runs_ms,omitempty"`
	Median         float64         `json:"median_ms,omitempty"`
	WorkRows       float64         `json:"work_rows"`
	Plan           json.RawMessage `json:"plan,omitempty"`
	Kind           string          `json:"kind"`
	Error          string          `json:"error,omitempty"`
}

func NewSQLBenchmark(t *testing.T, root, out string) pgx.QueryTracer {
	sqlMeasured.Lock()
	defer sqlMeasured.Unlock()
	if sqlMeasured.sites == nil {
		data, err := os.ReadFile(filepath.Join(out, "inventory.json"))
		if err != nil {
			t.Fatal(err)
		}
		if err = json.Unmarshal(data, &sqlMeasured.sites); err != nil {
			t.Fatal(err)
		}
	}
	return &sqlBenchmark{t: t, root: root, out: out}
}
func (b *sqlBenchmark) site() (sqlSite, bool) {
	pcs := make([]uintptr, 40)
	n := runtime.Callers(3, pcs)
	frames := runtime.CallersFrames(pcs[:n])
	for {
		f, more := frames.Next()
		rel, err := filepath.Rel(b.root, f.File)
		if err == nil {
			for _, s := range sqlMeasured.sites {
				if rel == s.File && f.Line >= s.Line && f.Line <= s.EndLine {
					return s, true
				}
			}
		}
		if !more {
			break
		}
	}
	return sqlSite{}, false
}
func (b *sqlBenchmark) TraceQueryStart(ctx context.Context, conn *pgx.Conn, data pgx.TraceQueryStartData) context.Context {
	if ctx.Value(sqlProbeKey{}) != nil {
		return ctx
	}
	site, ok := b.site()
	if !ok {
		return ctx
	}
	upper := strings.ToUpper(strings.TrimSpace(data.SQL))
	control := strings.HasPrefix(upper, "SAVEPOINT ") || strings.HasPrefix(upper, "ROLLBACK TO ")
	call := sqlCall{site: site, query: data.SQL, start: time.Now(), control: control}
	if control {
		return context.WithValue(ctx, sqlTraceKey{}, call)
	}
	if ctx.Err() != nil || conn.PgConn().TxStatus() == 'E' {
		return ctx
	}
	if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) < 5*time.Second {
		return ctx
	}
	key := fmt.Sprintf("%s:%d:%x", site.File, site.Line, sha256.Sum256([]byte(data.SQL)))
	sqlMeasured.Lock()
	state := sqlMeasured.seen[key]
	if state == nil {
		state = &sqlAttempt{}
		sqlMeasured.seen[key] = state
	}
	take := !state.busy && !state.matched && state.count < 4
	if take {
		state.busy = true
		state.count++
	}
	sqlMeasured.Unlock()
	if !take {
		return ctx
	}
	plans, err := b.probe(context.WithValue(ctx, sqlProbeKey{}, true), conn, data.SQL, data.Args)
	result := newSQLMeasurement(site, b.t.Name(), data.SQL, "explain_analyze", data.Args, plans)
	if err != nil {
		result.Kind = "probe_error"
		result.Error = sqlErrorCode(err)
	}
	b.record(result)
	sqlMeasured.Lock()
	state.busy = false
	state.matched = err == nil && result.WorkRows > 0
	sqlMeasured.Unlock()
	return ctx
}
func (b *sqlBenchmark) TraceQueryEnd(ctx context.Context, _ *pgx.Conn, data pgx.TraceQueryEndData) {
	call, ok := ctx.Value(sqlTraceKey{}).(sqlCall)
	if !ok || !call.control {
		return
	}
	r := sqlMeasurement{Site: call.site, Test: b.t.Name(), SQL: call.query, Kind: "control_client_elapsed", Runs: []float64{float64(time.Since(call.start)) / float64(time.Millisecond)}}
	r.Median = r.Runs[0]
	if data.Err != nil {
		r.Error = sqlErrorCode(data.Err)
	}
	b.record(r)
}
func sqlErrorCode(err error) string {
	if e, ok := err.(*pgconn.PgError); ok {
		return e.Code
	}
	return fmt.Sprintf("%T", err)
}

type sqlPlan struct {
	ExecutionTime float64         `json:"Execution Time"`
	Plan          map[string]any  `json:"Plan"`
	Raw           json.RawMessage `json:"-"`
}

func newSQLMeasurement(site sqlSite, test, query, kind string, args []any, plans []sqlPlan) sqlMeasurement {
	result := sqlMeasurement{Site: site, Test: test, SQL: query, Kind: kind}
	for _, arg := range args {
		result.ParameterTypes = append(result.ParameterTypes, fmt.Sprintf("%T", arg))
		size := 0
		switch v := arg.(type) {
		case []byte:
			size = len(v)
		case string:
			size = len(v)
		case []any:
			size = len(v)
		}
		result.ParameterSizes = append(result.ParameterSizes, size)
	}
	if len(plans) == 0 {
		return result
	}
	for _, plan := range plans[1:] {
		result.Runs = append(result.Runs, plan.ExecutionTime)
	}
	sorted := slices.Clone(result.Runs)
	slices.Sort(sorted)
	result.Median = sorted[len(sorted)/2]
	last := plans[len(plans)-1]
	result.Plan = last.Raw
	result.WorkRows = sqlWorkRows(last.Plan)
	return result
}

func (b *sqlBenchmark) probe(ctx context.Context, conn *pgx.Conn, query string, args []any) (plans []sqlPlan, err error) {
	nested := conn.PgConn().TxStatus() == 'T'
	begin, rollback := "BEGIN", "ROLLBACK"
	if nested {
		begin = "SAVEPOINT sql_benchmark_probe"
		rollback = "ROLLBACK TO SAVEPOINT sql_benchmark_probe"
	}
	for i := 0; i < 4; i++ {
		if _, err = conn.Exec(ctx, begin); err != nil {
			return nil, err
		}
		var raw []byte
		scanErr := conn.QueryRow(ctx, "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) "+query, args...).Scan(&raw)
		cleanup, cancel := context.WithTimeout(context.WithValue(context.Background(), sqlProbeKey{}, true), 5*time.Second)
		_, rollbackErr := conn.Exec(cleanup, rollback)
		if nested && rollbackErr == nil {
			_, rollbackErr = conn.Exec(cleanup, "RELEASE SAVEPOINT sql_benchmark_probe")
		}
		cancel()
		if rollbackErr != nil {
			return nil, rollbackErr
		}
		if scanErr != nil {
			return nil, scanErr
		}
		var decoded []sqlPlan
		if err = json.Unmarshal(raw, &decoded); err != nil {
			return nil, err
		}
		if len(decoded) != 1 {
			return nil, fmt.Errorf("expected one query plan")
		}
		decoded[0].Raw = append([]byte(nil), raw...)
		plans = append(plans, decoded[0])
	}
	return plans, nil
}
func sqlWorkRows(plan map[string]any) float64 {
	if n, ok := plan["Tuples Inserted"].(float64); ok {
		if plan["Conflict Resolution"] == "UPDATE" {
			conflicts, _ := plan["Conflicting Tuples"].(float64)
			filtered, _ := plan["Rows Removed by Conflict Filter"].(float64)
			n += conflicts - filtered
		}
		return n
	}
	if plan["Node Type"] == "ModifyTable" {
		if children, ok := plan["Plans"].([]any); ok {
			for _, child := range children {
				p, ok := child.(map[string]any)
				if ok && p["Parent Relationship"] == "Outer" {
					return sqlWorkRows(p)
				}
			}
		}
		return 0
	}
	n, _ := plan["Actual Rows"].(float64)
	return n
}
func (b *sqlBenchmark) record(r sqlMeasurement) {
	data, err := json.Marshal(r)
	if err != nil {
		b.t.Error(err)
		return
	}
	f, err := os.OpenFile(filepath.Join(b.out, fmt.Sprintf("queries-%d.jsonl", os.Getpid())), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		b.t.Error(err)
		return
	}
	_, err = f.Write(append(data, '\n'))
	closeErr := f.Close()
	if err != nil {
		b.t.Error(err)
	}
	if closeErr != nil {
		b.t.Error(closeErr)
	}
}
