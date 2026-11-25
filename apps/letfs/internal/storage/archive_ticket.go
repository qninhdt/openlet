package storage

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"time"

	"buf.build/go/protovalidate"
	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/genproto/googleapis/api/httpbody"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) CreateArchiveDownload(ctx context.Context, r *pb.DownloadArchiveRequest) (*pb.ArchiveDownloadTicket, error) {
	actor, err := s.check(ctx, "storage", r.StorageId, "read")
	if err != nil {
		return nil, err
	}
	resolvedTargets, err := resolve(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Targets, false, false)
	if err != nil {
		return nil, err
	}
	for _, t := range resolvedTargets {
		if t.Node == nil {
			return nil, notFound()
		}
	}
	raw, err := proto.Marshal(r)
	if err != nil {
		return nil, err
	}
	token := make([]byte, 32)
	if _, err = rand.Read(token); err != nil {
		return nil, err
	}
	ticket := hex.EncodeToString(token)
	digest := sha256.Sum256([]byte(ticket))
	expires := time.Now().Add(2 * time.Minute)
	_, err = s.DB.Exec(ctx, `INSERT INTO archive_downloads(ticket_hash,actor,request,expires_at) VALUES($1,$2,$3,$4)`, digest[:], actor.String(), raw, expires)
	return &pb.ArchiveDownloadTicket{Ticket: ticket, ExpiresAt: timestamppb.New(expires)}, err
}

type archiveStream struct {
	grpc.ServerStreamingServer[httpbody.HttpBody]
	ctx context.Context
}

func (s archiveStream) Context() context.Context { return s.ctx }

func (s *Server) consumeArchiveDownload(ctx context.Context, ticket string) (sdk.Actor, *pb.DownloadArchiveRequest, error) {
	digest := sha256.Sum256([]byte(ticket))
	var actor string
	var raw []byte
	err := s.DB.QueryRow(ctx, `DELETE FROM archive_downloads WHERE ticket_hash=$1 AND expires_at>now() RETURNING actor,request`, digest[:]).Scan(&actor, &raw)
	if err == pgx.ErrNoRows {
		return sdk.Actor{}, nil, status.Error(codes.NotFound, "download link has expired or was already used; start the download again")
	}
	if err != nil {
		return sdk.Actor{}, nil, err
	}
	kind, id, _ := strings.Cut(actor, ":")
	request := new(pb.DownloadArchiveRequest)
	if err = proto.Unmarshal(raw, request); err != nil {
		return sdk.Actor{}, nil, err
	}
	return sdk.Actor{Type: kind, ID: id}, request, nil
}

func (s *Server) DownloadArchiveTicket(r *pb.ArchiveDownloadTicketRequest, stream grpc.ServerStreamingServer[httpbody.HttpBody]) error {
	if err := protovalidate.Validate(r); err != nil {
		return invalid(err.Error())
	}
	actor, request, err := s.consumeArchiveDownload(stream.Context(), r.Ticket)
	if err != nil {
		return err
	}
	// Tickets grant one download of these targets; current permission is checked again without a cached revision.
	permission, err := s.Graph.CheckPermission(stream.Context(), &az.CheckPermissionRequest{Resource: sdk.Object("storage", request.StorageId), Permission: "read", Subject: sdk.Subject(actor), Consistency: &az.Consistency{Requirement: &az.Consistency_FullyConsistent{FullyConsistent: true}}})
	if err != nil {
		return err
	}
	if permission.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return permissionDenied()
	}
	ctx := metadata.NewIncomingContext(stream.Context(), metadata.Pairs("x-openlet-"+actor.Type+"-id", actor.ID))
	return s.DownloadArchive(request, archiveStream{ServerStreamingServer: stream, ctx: ctx})
}
