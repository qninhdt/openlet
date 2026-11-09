package grpc

import (
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

// Leta delegates the root resource identity, never raw-object or administrative access.
func LetaCredential(token string) rpc.Credential {
	methods := []string{
		letfsv1.FilesystemService_ResolveNode_FullMethodName,
		letfsv1.FilesystemService_BatchStat_FullMethodName,
		letfsv1.FilesystemService_ListNodes_FullMethodName,
		letfsv1.FilesystemService_Stat_FullMethodName,
		letfsv1.FilesystemService_ReadText_FullMethodName,
		letfsv1.FilesystemService_TextMetrics_FullMethodName,
		letfsv1.FilesystemService_ReadTree_FullMethodName,
		letfsv1.FilesystemService_TextSearch_FullMethodName,
		letfsv1.FilesystemService_SemanticSearch_FullMethodName,
		letfsv1.FilesystemService_ReadImage_FullMethodName,
		letfsv1.FilesystemService_WriteText_FullMethodName,
		letfsv1.FilesystemService_AppendText_FullMethodName,
		letfsv1.FilesystemService_PatchText_FullMethodName,
		letfsv1.FilesystemService_TruncateText_FullMethodName,
		letfsv1.FilesystemService_CreateNode_FullMethodName,
		letfsv1.FilesystemService_CreateDirectories_FullMethodName,
		letfsv1.FilesystemService_UpdateNode_FullMethodName,
		letfsv1.FilesystemService_CreateCopy_FullMethodName,
		letfsv1.FilesystemService_TrashNode_FullMethodName,
		letfsv1.FilesystemService_RestoreTrash_FullMethodName,
	}
	return rpc.Credential{Service: "leta", Token: token, DelegateActor: true, Methods: methods, LetaMethods: methods}
}
