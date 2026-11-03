package storage

import (
	"context"
	"encoding/base64"
	"net/url"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type SignedUpload struct {
	URL           string            `json:"url"`
	Headers       map[string]string `json:"headers"`
	ContentLength int64             `json:"content_length,string"`
	ExpiresAt     time.Time         `json:"expires_at"`
}

func signedUpload(request *v4.PresignedHTTPRequest, size int64, expires time.Time) SignedUpload {
	headers := map[string]string{}
	for key, values := range request.SignedHeader {
		key = strings.ToLower(key)
		// Browsers derive these headers from the URL/body; they cannot set them in JavaScript.
		if key != "host" && key != "content-length" {
			headers[key] = strings.Join(values, ",")
		}
	}
	return SignedUpload{URL: request.URL, Headers: headers, ContentLength: size, ExpiresAt: expires}
}

func (s *Client) SignPut(ctx context.Context, key string, size int64, md5 string, lifetime time.Duration) (SignedUpload, error) {
	return s.signPut(ctx, s.browser, key, size, md5, lifetime)
}

func (s *Client) ProcessorSignPut(ctx context.Context, key string, size int64, md5 string, lifetime time.Duration) (SignedUpload, error) {
	return s.signPut(ctx, s.processor, key, size, md5, lifetime)
}

func (s *Client) signPut(ctx context.Context, signer *s3.PresignClient, key string, size int64, md5 string, lifetime time.Duration) (SignedUpload, error) {
	checksum, err := base64.StdEncoding.DecodeString(md5)
	if !validKey(key) || size < 0 || lifetime < time.Second || lifetime > time.Hour || err != nil || len(checksum) != 16 || base64.StdEncoding.EncodeToString(checksum) != md5 {
		return SignedUpload{}, ErrInvalid
	}
	expires := time.Now().UTC().Add(lifetime)
	request, err := signer.PresignPutObject(ctx, &s3.PutObjectInput{Bucket: &s.bucket, Key: &key,
		ContentLength: &size, ContentMD5: &md5, IfNoneMatch: aws.String("*")}, func(options *s3.PresignOptions) { options.Expires = lifetime })
	if err != nil {
		return SignedUpload{}, providerError(err)
	}
	return signedUpload(request, size, expires), nil
}

func (s *Client) SignPart(ctx context.Context, key, upload string, number int32, size int64, lifetime time.Duration) (SignedUpload, error) {
	return s.signPart(ctx, s.browser, key, upload, number, size, lifetime)
}

func (s *Client) ProcessorSignPart(ctx context.Context, key, upload string, number int32, size int64, lifetime time.Duration) (SignedUpload, error) {
	return s.signPart(ctx, s.processor, key, upload, number, size, lifetime)
}

func (s *Client) signPart(ctx context.Context, signer *s3.PresignClient, key, upload string, number int32, size int64, lifetime time.Duration) (SignedUpload, error) {
	if !validKey(key) || upload == "" || number < 1 || number > 10000 || size < 0 || lifetime < time.Second || lifetime > time.Hour {
		return SignedUpload{}, ErrInvalid
	}
	expires := time.Now().UTC().Add(lifetime)
	request, err := signer.PresignUploadPart(ctx, &s3.UploadPartInput{Bucket: &s.bucket, Key: &key, UploadId: &upload, PartNumber: &number,
		ContentLength: &size}, func(options *s3.PresignOptions) { options.Expires = lifetime })
	if err != nil {
		return SignedUpload{}, providerError(err)
	}
	return signedUpload(request, size, expires), nil
}

func (s *Client) DownloadURL(ctx context.Context, key, name string, lifetime time.Duration) (string, error) {
	return s.downloadURL(ctx, s.browser, key, name, lifetime)
}

func (s *Client) ProcessorDownloadURL(ctx context.Context, key, name string, lifetime time.Duration) (string, error) {
	return s.downloadURL(ctx, s.processor, key, name, lifetime)
}

func (s *Client) downloadURL(ctx context.Context, signer *s3.PresignClient, key, name string, lifetime time.Duration) (string, error) {
	if !validKey(key) || lifetime < time.Second || lifetime > 10*time.Minute {
		return "", ErrInvalid
	}
	encoded := strings.ReplaceAll(url.QueryEscape(name), "+", "%20")
	disposition := "attachment; filename=\"download\"; filename*=UTF-8''" + encoded
	request, err := signer.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: &s.bucket, Key: &key,
		ResponseContentDisposition: &disposition, ResponseContentType: aws.String("application/octet-stream"),
		ResponseCacheControl: aws.String("private, no-store")}, func(options *s3.PresignOptions) { options.Expires = lifetime })
	if err != nil {
		return "", providerError(err)
	}
	return request.URL, nil
}
