package letfs

import (
	"context"
	"path"
	"strings"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type TextSearchOptions struct {
	Mode, Text                   string
	IgnoreCase                   bool
	MaxFiles, MaxLines, MaxBytes *int32
}

type TextSearchResult struct {
	Complete bool
	Items    []TreeEntry
	Content  []byte
	Stat     *FileStat
}

func nativeTextSearch(value *letfsv1.TextSearchResponse, scope uuid.UUID, locator Locator, options TextSearchOptions) (TextSearchResult, error) {
	if value == nil || options.Mode != "files" && options.Mode != "lines" {
		return TextSearchResult{}, scopeError()
	}
	if !value.Complete {
		if len(value.Items) > 0 || len(value.Content) > 0 || value.Stat != nil {
			return TextSearchResult{}, scopeError()
		}
		return TextSearchResult{Complete: false}, nil
	}
	result := TextSearchResult{Complete: true, Items: []TreeEntry{}, Content: value.Content}
	if options.Mode == "lines" {
		stat, err := nativeStat(value.Stat, scope, &locator)
		if err != nil {
			return TextSearchResult{}, err
		}
		if len(value.Items) != 0 || stat.Node.Kind != "file" || int64(len(value.Content)) > stat.ReadableSize {
			return TextSearchResult{}, scopeError()
		}
		result.Stat = &stat
	} else {
		if value.Stat != nil || len(value.Content) != 0 || options.MaxFiles != nil && len(value.Items) > int(*options.MaxFiles) {
			return TextSearchResult{}, scopeError()
		}
		seen := map[uuid.UUID]bool{}
		last := ""
		for _, item := range value.Items {
			stat, err := nativeStat(item.GetStat(), scope, nil)
			if err != nil {
				return TextSearchResult{}, err
			}
			p := item.GetPath()
			if p == "" || p == "." || path.IsAbs(p) || path.Clean(p) != p || p == ".." || strings.HasPrefix(p, "../") || stat.Node.Kind != "file" || seen[stat.Node.ID] || p <= last {
				return TextSearchResult{}, scopeError()
			}
			seen[stat.Node.ID], last = true, p
			result.Items = append(result.Items, TreeEntry{Path: p, Stat: stat})
		}
	}
	return result, nil
}

func (c FilesystemClient) TextSearch(ctx context.Context, fs, scope uuid.UUID, locator Locator, options TextSearchOptions) (TextSearchResult, error) {
	loc, err := nativeLocator(locator)
	if err != nil {
		return TextSearchResult{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.TextSearch(ctx, &letfsv1.TextSearchRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: loc, Mode: options.Mode, Text: options.Text, IgnoreCase: options.IgnoreCase, MaxFiles: options.MaxFiles, MaxLines: options.MaxLines, MaxBytes: options.MaxBytes})
	if err != nil {
		return TextSearchResult{}, rpc.DecodeError(err)
	}
	return nativeTextSearch(response, scope, locator, options)
}
