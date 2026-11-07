package main

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

type entry struct {
	File     string `json:"file"`
	Line     int    `json:"line"`
	EndLine  int    `json:"end_line"`
	Function string `json:"function"`
	Call     string `json:"call"`
	SQL      string `json:"sql_expression"`
}

func main() {
	var rows []entry
	fs := token.NewFileSet()
	for _, root := range []string{"apps/account/internal", "apps/workspace/internal", "apps/letfs/internal", "packages/go"} {
		err := filepath.WalkDir(root, func(path string, d os.DirEntry, e error) error {
			if e != nil {
				return e
			}
			if d.IsDir() {
				if d.Name() == "gen" {
					return filepath.SkipDir
				}
				return nil
			}
			if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			f, e := parser.ParseFile(fs, path, nil, 0)
			if e != nil {
				return e
			}
			for _, decl := range f.Decls {
				fn, ok := decl.(*ast.FuncDecl)
				if !ok {
					continue
				}
				ast.Inspect(fn.Body, func(n ast.Node) bool {
					c, ok := n.(*ast.CallExpr)
					if !ok {
						return true
					}
					sel, ok := c.Fun.(*ast.SelectorExpr)
					if !ok {
						return true
					}
					idx := 1
					switch sel.Sel.Name {
					case "Query", "QueryRow", "Exec":
					case "Queue":
						idx = 0
					default:
						return true
					}
					if len(c.Args) <= idx {
						return true
					}
					var q, b bytes.Buffer
					format.Node(&q, fs, c.Args[idx])
					format.Node(&b, fs, sel.X)
					s := q.String()
					recv := b.String()
					if !strings.ContainsAny(s, "`\"") && !strings.Contains(strings.ToLower(recv), "tx") && !strings.Contains(strings.ToLower(recv), "db") && !strings.Contains(strings.ToLower(recv), "batch") {
						return true
					}
					rows = append(rows, entry{path, fs.Position(c.Pos()).Line, fs.Position(c.End()).Line, fn.Name.Name, recv + "." + sel.Sel.Name, s})
					return true
				})
			}
			return nil
		})
		if err != nil {
			panic(err)
		}
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(rows); err != nil {
		panic(err)
	}
}
