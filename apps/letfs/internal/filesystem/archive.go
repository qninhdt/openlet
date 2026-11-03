package filesystem

import (
	"archive/zip"
	"bytes"
	"context"
	"io"
	"slices"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
	"golang.org/x/text/unicode/norm"
)

type ArchiveConfig struct {
	MaxEntries, MaxSourceBytes, MaxOutputBytes int64
	Runtime                                    time.Duration
}

func (c ArchiveConfig) Validate() error {
	if c.MaxEntries < 1 || c.MaxEntries > 100000 || c.MaxSourceBytes < 1 || c.MaxSourceBytes > 10000000000 || c.MaxOutputBytes < 1 || c.MaxOutputBytes > 10000000000 || c.Runtime < time.Second || c.Runtime > 1800*time.Second {
		return enrichmentValidation("invalid archive resource limits")
	}
	return nil
}

type archiveEntry struct {
	ID               uuid.UUID
	Parent           pgtype.UUID
	Name, Path, Kind string
	Revision, Size   int64
	Key              pgtype.Text
}

type archivePlan struct {
	FilesystemID uuid.UUID
	Name         string
	Entries      []archiveEntry
}

type ArchiveStream struct {
	Name    string
	Context context.Context
	reader  *io.PipeReader
	cancel  context.CancelFunc
	done    chan struct{}
	release func()
	once    sync.Once
}

func (s *ArchiveStream) Read(p []byte) (int, error) { return s.reader.Read(p) }
func (s *ArchiveStream) Close() error {
	s.once.Do(func() {
		s.cancel()
		_ = s.reader.Close()
		<-s.done
		s.release()
	})
	return nil
}

func safeArchiveComponent(value string) error {
	if err := ValidateName(value); err != nil {
		return err
	}
	stem := strings.ToUpper(strings.SplitN(value, ".", 2)[0])
	reserved := stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL"
	if strings.HasPrefix(stem, "COM") || strings.HasPrefix(stem, "LPT") {
		suffix := stem[3:]
		reserved = reserved || len([]rune(suffix)) == 1 && strings.ContainsAny(suffix, "123456789¹²³")
	}
	if reserved || strings.HasSuffix(value, ".") || strings.HasSuffix(value, " ") || strings.ContainsAny(value, `\:<>"|?*`) || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return enrichmentValidation("unsafe archive name")
	}
	return nil
}

func archiveCollisionKey(value string) string {
	return norm.NFC.String(strings.ToLower(norm.NFC.String(value)))
}

func (s *Store) preflightArchive(ctx context.Context, fs uuid.UUID, mounts []Mount, id uuid.UUID) (archivePlan, error) {
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return archivePlan{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, Locator{NodeID: &id})
	if err != nil {
		return archivePlan{}, err
	}
	if err = node.directory(); err != nil {
		return archivePlan{}, err
	}
	rows, err := session.tx.Query(ctx, `WITH RECURSIVE tree AS (
 SELECT n.*,''::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE n.filesystem_id=$1 AND n.id=$2
 UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1 FROM tree t JOIN nodes n ON n.filesystem_id=$1 AND n.parent_id=t.id WHERE t.kind='directory' AND t.depth<128)
 SELECT t.id,t.parent_id,t.name,t.path,t.kind,t.revision,t.size_bytes,f.object_key,f.storage_kind FROM tree t LEFT JOIN files f ON f.node_id=t.id LIMIT $3`, fs, id, s.Archive.MaxEntries+2)
	if err != nil {
		return archivePlan{}, databaseError(err)
	}
	defer rows.Close()
	result := archivePlan{FilesystemID: fs, Name: node.Name + ".zip"}
	names, total := make(map[string]bool), int64(0)
	for rows.Next() {
		var entry archiveEntry
		var storage pgtype.Text
		if err = rows.Scan(&entry.ID, &entry.Parent, &entry.Name, &entry.Path, &entry.Kind, &entry.Revision, &entry.Size, &entry.Key, &storage); err != nil {
			return result, databaseError(err)
		}
		if len(result.Entries) >= int(s.Archive.MaxEntries)+1 || entry.Size < 0 || entry.Size > s.Archive.MaxSourceBytes-total {
			return result, archiveLimit()
		}
		total += entry.Size
		if entry.ID != id {
			for _, part := range strings.Split(entry.Path, "/") {
				if err = safeArchiveComponent(part); err != nil {
					return result, err
				}
			}
			key := archiveCollisionKey(entry.Path)
			if len(entry.Path) > 4096 || names[key] {
				return result, enrichmentValidation("ambiguous archive path")
			}
			names[key] = true
		}
		if entry.Kind == "file" && !storage.Valid {
			return result, uploadState("SOURCE_CHANGED")
		}
		result.Entries = append(result.Entries, entry)
	}
	if err = rows.Err(); err != nil {
		return result, databaseError(err)
	}
	slices.SortFunc(result.Entries, func(a, b archiveEntry) int { return strings.Compare(a.Path, b.Path) })
	return result, nil
}

func archiveLimit() error {
	return apperr.New(apperr.Limit, "RESOURCE_LIMIT", "archive resource limit")
}

func (s *Store) OpenArchive(ctx context.Context, fs uuid.UUID, mounts []Mount, id uuid.UUID) (*ArchiveStream, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.Archive); err != nil {
		return nil, err
	}
	if s.Archive.Validate() != nil || s.ArchiveSlots == nil {
		return nil, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "archive configuration unavailable")
	}
	if !s.ArchiveSlots.TryAcquire(1) {
		return nil, archiveLimit()
	}
	ctx, cancel := context.WithTimeout(ctx, s.Archive.Runtime)
	plan, err := s.preflightArchive(ctx, fs, mounts, id)
	if err != nil {
		cancel()
		s.ArchiveSlots.Release(1)
		return nil, err
	}
	reader, writer := io.Pipe()
	result := &ArchiveStream{Name: plan.Name, Context: ctx, reader: reader, cancel: cancel, done: make(chan struct{}), release: func() { s.ArchiveSlots.Release(1) }}
	stop := context.AfterFunc(ctx, func() { _ = writer.CloseWithError(ctx.Err()) })
	go func() {
		defer close(result.done)
		defer stop()
		err := s.produceArchive(ctx, plan, writer)
		_ = writer.CloseWithError(err)
	}()
	return result, nil
}

func (s *Store) archivePayload(ctx context.Context, plan archivePlan, entry archiveEntry, expected map[uuid.UUID]archiveEntry) ([]byte, error) {
	session, err := s.openSession(ctx, plan.FilesystemID, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	rows, err := session.tx.Query(ctx, `WITH RECURSIVE ancestors AS (
 SELECT n.*,0 AS depth FROM nodes n WHERE n.id=$1 AND n.filesystem_id=$2
 UNION ALL SELECT n.*,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2 WHERE a.id!=$3 AND a.depth<128)
 SELECT a.id,a.parent_id,a.name,a.kind,a.revision,a.size_bytes,f.object_key,CASE WHEN a.id=$1 THEN f.inline_bytes END FROM ancestors a LEFT JOIN files f ON f.node_id=a.id ORDER BY depth`, entry.ID, plan.FilesystemID, session.root)
	if err != nil {
		return nil, databaseError(err)
	}
	defer rows.Close()
	var inline []byte
	last := uuid.Nil
	for rows.Next() {
		var current archiveEntry
		var content []byte
		if err = rows.Scan(&current.ID, &current.Parent, &current.Name, &current.Kind, &current.Revision, &current.Size, &current.Key, &content); err != nil {
			return nil, databaseError(err)
		}
		last = current.ID
		if last == entry.ID {
			inline = content
		}
		if prior, ok := expected[last]; ok && (prior.Parent != current.Parent || prior.Name != current.Name || prior.Kind != current.Kind || prior.Revision != current.Revision || prior.Size != current.Size || prior.Key != current.Key) {
			return nil, uploadState("SOURCE_CHANGED")
		}
	}
	if err = rows.Err(); err != nil {
		return nil, databaseError(err)
	}
	if last != session.root {
		return nil, uploadState("SOURCE_CHANGED")
	}
	return inline, nil
}

type archiveOutput struct {
	io.Writer
	remaining int64
}

func (w *archiveOutput) Write(p []byte) (int, error) {
	if int64(len(p)) > w.remaining {
		return 0, archiveLimit()
	}
	n, err := w.Writer.Write(p)
	w.remaining -= int64(n)
	return n, err
}

func (s *Store) produceArchive(ctx context.Context, plan archivePlan, output io.Writer) error {
	writer := zip.NewWriter(&archiveOutput{Writer: output, remaining: s.Archive.MaxOutputBytes})
	expected := make(map[uuid.UUID]archiveEntry, len(plan.Entries))
	for _, entry := range plan.Entries {
		expected[entry.ID] = entry
	}
	buffer := make([]byte, 65536)
	for _, entry := range plan.Entries {
		inline, err := s.archivePayload(ctx, plan, entry, expected)
		if err != nil {
			return err
		}
		if entry.Path == "" {
			continue
		}
		path := entry.Path
		if entry.Kind == "directory" {
			path += "/"
		}
		destination, err := writer.CreateHeader(&zip.FileHeader{Name: path, Method: zip.Store})
		if err != nil {
			if apperr.KindOf(err) != apperr.Internal {
				return err
			}
			return apperr.New(apperr.Internal, "ARCHIVE_FAILED", "archive stream failed")
		}
		if entry.Kind != "file" {
			continue
		}
		if err = s.writeArchiveFile(ctx, destination, entry, inline, buffer); err != nil {
			return err
		}
	}
	return writer.Close()
}

func (s *Store) writeArchiveFile(ctx context.Context, destination io.Writer, entry archiveEntry, inline, buffer []byte) error {
	var source io.Reader = bytes.NewReader(inline)
	if entry.Key.Valid {
		if s.Storage == nil {
			return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
		input, err := s.Storage.Open(ctx, entry.Key.String)
		if err != nil {
			return databaseError(err)
		}
		defer input.Close()
		source = input
	} else if inline == nil {
		return uploadState("SOURCE_CHANGED")
	}
	count, err := io.CopyBuffer(destination, io.LimitReader(source, entry.Size+1), buffer)
	if err != nil {
		return err
	}
	if count != entry.Size {
		return uploadState("SOURCE_CHANGED")
	}
	return nil
}
