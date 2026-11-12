package sdk

import (
	"context"
	"fmt"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/authzed/grpcutil"
	"github.com/exaring/otelpgx"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type Runtime struct {
	Environment            string `yaml:"environment"`
	LogLevel               string `yaml:"log_level"`
	ShutdownTimeoutSeconds int    `yaml:"shutdown_timeout_seconds"`
}
type GRPC struct {
	MaxReceiveBytes int `yaml:"max_receive_bytes"`
}
type Postgres struct {
	Host    string `yaml:"host"`
	Port    uint16 `yaml:"port"`
	SSLMode string `yaml:"sslmode"`
}
type Database struct {
	Name     string `yaml:"name"`
	User     string `yaml:"user"`
	Password string `yaml:"password"`
}
type SpiceDB struct {
	Address string `yaml:"address"`
	TLS     bool   `yaml:"tls"`
	Key     string `yaml:"key"`
}
type Queues struct {
	Platform    string `yaml:"platform"`
	LetFS       string `yaml:"letfs"`
	IngestCPU   string `yaml:"ingest_cpu"`
	IngestIO    string `yaml:"ingest_io"`
	Leta        string `yaml:"leta"`
	LetaRuntime string `yaml:"leta_runtime"`
}
type Temporal struct {
	Address   string `yaml:"address"`
	Namespace string `yaml:"namespace"`
	TLS       bool   `yaml:"tls"`
	Queues    Queues `yaml:"queues"`
}

func OpenDatabase(ctx context.Context, p Postgres, d Database) (*pgxpool.Pool, error) {
	password, err := Secret("database.password", d.Password)
	if err != nil {
		return nil, err
	}
	c, err := pgxpool.ParseConfig("sslmode=" + p.SSLMode)
	if err != nil {
		return nil, err
	}
	c.ConnConfig.Tracer = otelpgx.NewTracer(otelpgx.WithDisableSQLStatementInAttributes())
	c.ConnConfig.Host = p.Host
	c.ConnConfig.Port = p.Port
	c.ConnConfig.Database = d.Name
	c.ConnConfig.User = d.User
	c.ConnConfig.Password = password
	pool, err := pgxpool.NewWithConfig(ctx, c)
	if err != nil {
		return nil, err
	}
	if err = pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	if err = otelpgx.RecordStats(pool); err != nil {
		pool.Close()
		return nil, err
	}
	return pool, nil
}
func OpenSpiceDB(c SpiceDB) (*authzed.Client, error) {
	key, err := Secret("dependencies.spicedb.key", c.Key)
	if err != nil {
		return nil, err
	}
	var options []grpc.DialOption
	if c.TLS {
		tc, err := grpcutil.WithSystemCerts(grpcutil.VerifyCA)
		if err != nil {
			return nil, err
		}
		options = append(options, tc, grpcutil.WithBearerToken(key))
	} else {
		options = append(options, grpc.WithTransportCredentials(insecure.NewCredentials()), grpcutil.WithInsecureBearerToken(key))
	}
	options = append(options, grpc.WithStatsHandler(otelgrpc.NewClientHandler()))
	return authzed.NewClient(c.Address, options...)
}
func Dial(target string) (*grpc.ClientConn, error) {
	if target == "" {
		return nil, fmt.Errorf("gRPC target is required")
	}
	return grpc.NewClient(target, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithStatsHandler(otelgrpc.NewClientHandler()))
}
