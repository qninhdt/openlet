package sdk

import (
	"context"
	"errors"
	"log/slog"

	"buf.build/go/protovalidate"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

func Validation() (grpc.UnaryServerInterceptor, error) {
	v, err := protovalidate.New()
	if err != nil {
		return nil, err
	}
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, next grpc.UnaryHandler) (any, error) {
		if p, ok := req.(proto.Message); ok {
			if err := v.Validate(p); err != nil {
				return nil, status.Error(codes.InvalidArgument, err.Error())
			}
		}
		out, err := next(ctx, req)
		if err == nil {
			return out, nil
		}
		if _, ok := status.FromError(err); ok {
			return nil, err
		}
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, status.Error(codes.NotFound, "resource not found")
		}
		var db *pgconn.PgError
		if errors.As(err, &db) {
			switch db.Code {
			case "23505":
				return nil, status.Error(codes.AlreadyExists, "name or identity already exists")
			case "23503":
				return nil, status.Error(codes.FailedPrecondition, "referenced resource is unavailable")
			case "40001", "40P01":
				return nil, status.Error(codes.Aborted, "concurrent update; retry the command")
			}
		}
		if errors.Is(err, context.Canceled) {
			return nil, status.Error(codes.Canceled, "request canceled")
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, status.Error(codes.DeadlineExceeded, "request deadline exceeded")
		}
		slog.ErrorContext(ctx, "RPC failed", "method", info.FullMethod, "error", err)
		return nil, status.Error(codes.Internal, "operation failed")
	}, nil
}
