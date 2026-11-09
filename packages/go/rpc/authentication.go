package rpc

import (
	"context"
	"crypto/subtle"
	"errors"
	"slices"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/identity"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type Credential struct {
	Service       string
	Token         string
	Methods       []string
	Gateway       bool
	DelegateActor bool
	LetaMethods   []string
}

type Authenticator struct{ credentials []Credential }

func validServiceToken(token string) bool {
	return len(token) >= 32 && strings.IndexFunc(token, func(r rune) bool {
		return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
	}) < 0
}

func NewAuthenticator(credentials []Credential) (*Authenticator, error) {
	result := &Authenticator{}
	seen := make(map[string]bool)
	for _, credential := range credentials {
		if credential.Service == "" || !validServiceToken(credential.Token) || len(credential.Methods) == 0 || seen[credential.Token] {
			return nil, errors.New("invalid RPC credential configuration")
		}
		seen[credential.Token] = true
		credential.Methods = append([]string(nil), credential.Methods...)
		credential.LetaMethods = append([]string(nil), credential.LetaMethods...)
		for _, method := range credential.LetaMethods {
			if !slices.Contains(credential.Methods, method) || credential.Gateway || !credential.DelegateActor {
				return nil, errors.New("invalid Leta delegation allowlist")
			}
		}
		for _, method := range credential.Methods {
			if !strings.HasPrefix(method, "/openlet_api.") || strings.Count(method, "/") != 2 {
				return nil, errors.New("invalid RPC method allowlist")
			}
		}
		result.credentials = append(result.credentials, credential)
	}
	if len(result.credentials) == 0 {
		return nil, errors.New("missing RPC credentials")
	}
	return result, nil
}

// Authenticate verifies native gRPC caller identity and method scope.
func (a *Authenticator) Authenticate(ctx context.Context, method string) (context.Context, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	users, letas := md.Get("x-openlet-user-id"), md.Get("x-openlet-leta-id")
	if len(md.Get("authorization")) != 1 || len(users)+len(letas) > 1 || len(md.Get("x-openlet-service")) != 0 || len(md.Get("x-openlet-account-id")) != 0 {
		return nil, status.Error(codes.Unauthenticated, "invalid caller metadata")
	}
	token, ok := strings.CutPrefix(md.Get("authorization")[0], "Bearer ")
	if !ok || token == "" {
		return nil, status.Error(codes.Unauthenticated, "missing caller credential")
	}
	for _, credential := range a.credentials {
		if subtle.ConstantTimeCompare([]byte(token), []byte(credential.Token)) != 1 {
			continue
		}
		if !slices.Contains(credential.Methods, method) {
			return nil, status.Error(codes.PermissionDenied, "caller cannot invoke method")
		}
		principal := identity.Principal{Service: credential.Service, Gateway: credential.Gateway}
		actors, kind := users, identity.User
		if len(letas) != 0 {
			actors, kind = letas, identity.Leta
			if !slices.Contains(credential.LetaMethods, method) {
				return nil, status.Error(codes.PermissionDenied, "caller cannot delegate Leta")
			}
		}
		if len(actors) == 1 {
			if !credential.Gateway && !credential.DelegateActor {
				return nil, status.Error(codes.PermissionDenied, "caller cannot delegate user")
			}
			actor, err := uuid.Parse(actors[0])
			if err != nil || actor == uuid.Nil {
				return nil, status.Error(codes.Unauthenticated, "invalid actor identity")
			}
			principal.ActorID = actor
			principal.ActorKind = kind
		} else if credential.Gateway {
			return nil, status.Error(codes.Unauthenticated, "missing actor identity")
		}
		return identity.WithPrincipal(ctx, principal), nil
	}
	return nil, status.Error(codes.Unauthenticated, "invalid caller credential")
}

func (a *Authenticator) Unary() grpc.UnaryServerInterceptor {
	return func(ctx context.Context, request any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		ctx, err := a.Authenticate(ctx, info.FullMethod)
		if err != nil {
			return nil, err
		}
		response, err := handler(ctx, request)
		return response, NormalizeError(err)
	}
}

type authenticatedStream struct {
	grpc.ServerStream
	ctx context.Context
}

func (s *authenticatedStream) Context() context.Context { return s.ctx }

func (a *Authenticator) Stream() grpc.StreamServerInterceptor {
	return func(server any, stream grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
		ctx, err := a.Authenticate(stream.Context(), info.FullMethod)
		if err != nil {
			return err
		}
		return NormalizeError(handler(server, &authenticatedStream{ServerStream: stream, ctx: ctx}))
	}
}
