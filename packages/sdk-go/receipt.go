package sdk

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

// Claim and Finish run in the same transaction as the local SQL effect.
func Claim(ctx context.Context, tx pgx.Tx, caller, method, key string, request, result proto.Message, ttl time.Duration) (bool, error) {
	b, err := proto.MarshalOptions{Deterministic: true}.Marshal(request)
	if err != nil {
		return false, err
	}
	hash := sha256.Sum256(b)
	tag, err := tx.Exec(ctx, `INSERT INTO idempotency_keys(caller,method,key,request_hash,expires_at) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, caller, method, key, hash[:], time.Now().Add(ttl))
	if err != nil {
		return false, err
	}
	if tag.RowsAffected() == 1 {
		return false, nil
	}
	return Replay(ctx, tx, caller, method, key, request, result)
}

// Replay checks completed receipts before nontransactional upload side effects.
func Replay(ctx context.Context, db interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, caller, method, key string, request, result proto.Message) (bool, error) {
	var storedHash, storedResult []byte
	err := db.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys WHERE caller=$1 AND method=$2 AND key=$3`, caller, method, key).Scan(&storedHash, &storedResult)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	b, err := proto.MarshalOptions{Deterministic: true}.Marshal(request)
	if err != nil {
		return false, err
	}
	hash := sha256.Sum256(b)
	if !bytes.Equal(hash[:], storedHash) {
		return false, status.Error(codes.AlreadyExists, "request_id was used with another payload")
	}
	if err = proto.Unmarshal(storedResult, result); err != nil {
		return false, err
	}
	return true, nil
}
func Finish(ctx context.Context, tx pgx.Tx, caller, method, key string, result proto.Message) error {
	b, err := proto.Marshal(result)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `UPDATE idempotency_keys SET result=$4 WHERE caller=$1 AND method=$2 AND key=$3`, caller, method, key, b)
	return err
}
