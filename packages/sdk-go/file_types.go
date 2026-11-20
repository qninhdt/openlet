package sdk

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"strings"
)

type FileKind string

const (
	FileText        FileKind = "text"
	FileBlob        FileKind = "blob"
	FileUnsupported FileKind = "unsupported"
)

type FileTypes map[FileKind]map[string]string

func LoadFileTypes(filename string) (FileTypes, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}
	var types FileTypes
	if err = json.Unmarshal(data, &types); err != nil {
		return nil, fmt.Errorf("parse %s: %w", filename, err)
	}
	if len(types[FileText]) == 0 || len(types[FileBlob]) == 0 {
		return nil, fmt.Errorf("%s must define text and blob file extensions", filename)
	}
	return types, nil
}

func (types FileTypes) ClassifyExtension(extension string) (FileKind, string) {
	extension = strings.ToLower(strings.TrimPrefix(extension, "."))
	if media := types[FileText][extension]; media != "" {
		return FileText, media
	}
	if media := types[FileBlob][extension]; media != "" {
		return FileBlob, media
	}
	return FileUnsupported, ""
}

func (types FileTypes) ClassifyFile(name string) (FileKind, string) {
	base := path.Base(name)
	extension := path.Ext(base)
	if len(extension) == len(base) {
		return FileUnsupported, ""
	}
	return types.ClassifyExtension(extension)
}
