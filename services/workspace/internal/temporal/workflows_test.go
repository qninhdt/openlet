//go:build workflow

package temporal

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"openlet/services/workspace/internal/workspace"
)

func TestCreateWorkspace(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.CreateInput{ActorID: uuid.Must(uuid.NewV7()), Key: uuid.Must(uuid.NewV7()), Name: "Workspace"}
	p := workspace.Provision{Operation: workspace.Operation{ID: uuid.Must(uuid.NewV7())}, Storage: workspace.Storage{WorkspaceID: uuid.Must(uuid.NewV7()), BucketID: uuid.Must(uuid.NewV7()), FilesystemID: uuid.Must(uuid.NewV7()), RootID: uuid.Must(uuid.NewV7()), LimitBytes: "100"}}
	a := &Activities{}
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(p, nil).Once()
	env.OnActivity(a.EnsureStorageBucket, mock.Anything, p.Storage).Return(nil).Once()
	env.OnActivity(a.EnsureDriveFilesystem, mock.Anything, p.Storage).Return(nil).Once()
	env.OnActivity(a.ActivateWorkspace, mock.Anything, p.Operation.ID).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	if e := env.GetWorkflowError(); e != nil {
		t.Fatal(e)
	}
	var id uuid.UUID
	if e := env.GetWorkflowResult(&id); e != nil || id != p.Operation.ID {
		t.Fatal(id, e)
	}
	env.AssertExpectations(t)
}
func TestCreateWorkspaceRejectsBeforeProvisioning(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.CreateInput{Name: "bad"}
	a := &Activities{}
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(workspace.Provision{}, temporal.NewNonRetryableApplicationError("rejected", "VALIDATION", nil)).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	if env.GetWorkflowError() == nil {
		t.Fatal("expected rejection")
	}
	env.AssertExpectations(t)
}

func TestCreateWorkspaceFailureRetainsAdmission(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.CreateInput{ActorID: uuid.Must(uuid.NewV7()), Key: uuid.Must(uuid.NewV7()), Name: "Workspace"}
	p := workspace.Provision{Operation: workspace.Operation{ID: uuid.Must(uuid.NewV7())}}
	a := &Activities{}
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(p, nil).Once()
	env.OnActivity(a.EnsureStorageBucket, mock.Anything, p.Storage).Return(temporal.NewNonRetryableApplicationError("scope conflict", "SCOPE_CONFLICT", nil)).Once()
	env.OnActivity(a.FailWorkspace, mock.Anything, p.Operation.ID).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	if env.GetWorkflowError() == nil {
		t.Fatal("expected failure")
	}
	env.AssertExpectations(t)
}
