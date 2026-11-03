package storage

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
)

var (
	ErrNotFound     = errors.New("object not found")
	ErrPrecondition = errors.New("object precondition failed")
	ErrUnavailable  = errors.New("object storage unavailable")
	ErrInvalid      = errors.New("invalid object storage input")
)

type Config struct {
	Endpoint, SigningEndpoint, Region, Bucket, AccessKey, SecretKey string
	AllowHTTP                                                       bool
}

type Client struct {
	control            *s3.Client
	browser, processor *s3.PresignClient
	bucket             string
}

func New(config Config) (*Client, error) {
	if config.SigningEndpoint == "" {
		config.SigningEndpoint = config.Endpoint
	}
	for _, endpoint := range []string{config.Endpoint, config.SigningEndpoint} {
		parsed, err := url.Parse(endpoint)
		if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" ||
			!(parsed.Scheme == "https" || config.AllowHTTP && parsed.Scheme == "http") {
			return nil, errors.New("invalid S3 endpoint; HTTPS required unless local storage is enabled")
		}
	}
	if config.Region == "" || config.Bucket == "" || strings.ContainsAny(config.Bucket, "/\x00\r\n") || config.AccessKey == "" || config.SecretKey == "" {
		return nil, errors.New("S3 region, bucket and credentials required")
	}
	build := func(endpoint string) *s3.Client {
		return s3.New(s3.Options{
			Region: config.Region, BaseEndpoint: aws.String(endpoint), UsePathStyle: true,
			Credentials: aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
				return aws.Credentials{AccessKeyID: config.AccessKey, SecretAccessKey: config.SecretKey, Source: "letfs-config"}, nil
			}),
			// Durable callers account for each write; the SDK must not repeat an unknown effect.
			Retryer: aws.NopRetryer{}, RequestChecksumCalculation: aws.RequestChecksumCalculationWhenRequired,
			ResponseChecksumValidation: aws.ResponseChecksumValidationWhenRequired,
			HTTPClient:                 &http.Client{Timeout: 120 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
		})
	}
	control := build(config.Endpoint)
	browser := control
	if config.SigningEndpoint != config.Endpoint {
		browser = build(config.SigningEndpoint)
	}
	return &Client{control: control, browser: s3.NewPresignClient(browser), processor: s3.NewPresignClient(control), bucket: config.Bucket}, nil
}

func validKey(key string) bool {
	return key != "" && len(key) <= 1024 && utf8.ValidString(key) && !strings.ContainsRune(key, '\x00')
}

func providerError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	var api smithy.APIError
	if errors.As(err, &api) {
		switch api.ErrorCode() {
		case "NotFound", "NoSuchKey", "NoSuchUpload":
			return ErrNotFound
		case "PreconditionFailed", "ConditionalRequestConflict":
			return ErrPrecondition
		}
	}
	return ErrUnavailable
}

type Object struct {
	Size int64
	ETag string
}

func (s *Client) Head(ctx context.Context, key string) (Object, error) {
	if !validKey(key) {
		return Object{}, ErrInvalid
	}
	response, err := s.control.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.bucket, Key: &key})
	if err != nil {
		return Object{}, providerError(err)
	}
	if response.ContentLength == nil || *response.ContentLength < 0 {
		return Object{}, ErrUnavailable
	}
	return Object{Size: *response.ContentLength, ETag: aws.ToString(response.ETag)}, nil
}

func (s *Client) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	if !validKey(key) {
		return nil, ErrInvalid
	}
	response, err := s.control.GetObject(ctx, &s3.GetObjectInput{Bucket: &s.bucket, Key: &key})
	if err != nil {
		return nil, providerError(err)
	}
	return response.Body, nil
}

func (s *Client) Copy(ctx context.Context, source, destination string) error {
	if !validKey(source) || !validKey(destination) {
		return ErrInvalid
	}
	copySource := url.PathEscape(s.bucket + "/" + source)
	_, err := s.control.CopyObject(ctx, &s3.CopyObjectInput{Bucket: &s.bucket, Key: &destination, CopySource: &copySource})
	return providerError(err)
}

func (s *Client) Delete(ctx context.Context, key string) error {
	if !validKey(key) {
		return ErrInvalid
	}
	_, err := s.control.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: &s.bucket, Key: &key})
	return providerError(err)
}

func (s *Client) CreateMultipart(ctx context.Context, key string) (string, error) {
	if !validKey(key) {
		return "", ErrInvalid
	}
	response, err := s.control.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{Bucket: &s.bucket, Key: &key})
	if err != nil {
		return "", providerError(err)
	}
	if response.UploadId == nil || *response.UploadId == "" {
		return "", ErrUnavailable
	}
	return *response.UploadId, nil
}

type PartReceipt struct {
	Number int32  `json:"part_number"`
	ETag   string `json:"etag"`
}

func (s *Client) CompleteMultipart(ctx context.Context, key, upload string, receipts []PartReceipt) error {
	if !validKey(key) || upload == "" || len(receipts) == 0 || len(receipts) > 10000 {
		return ErrInvalid
	}
	parts := make([]types.CompletedPart, len(receipts))
	for i, receipt := range receipts {
		if receipt.Number != int32(i+1) || receipt.ETag == "" || len(receipt.ETag) > 1024 || strings.IndexFunc(receipt.ETag, func(r rune) bool { return r < 32 || r == 127 }) >= 0 {
			return ErrInvalid
		}
		parts[i] = types.CompletedPart{PartNumber: aws.Int32(receipt.Number), ETag: aws.String(receipt.ETag)}
	}
	_, err := s.control.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{Bucket: &s.bucket, Key: &key, UploadId: &upload,
		MultipartUpload: &types.CompletedMultipartUpload{Parts: parts}})
	return providerError(err)
}

func (s *Client) AbortMultipart(ctx context.Context, key, upload string) error {
	if !validKey(key) || upload == "" {
		return ErrInvalid
	}
	_, err := s.control.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{Bucket: &s.bucket, Key: &key, UploadId: &upload})
	return providerError(err)
}
