use super::activity_error;
use crate::{
    fs::{Bucket, Filesystem, provisioning},
    http::App,
};
use std::sync::Arc;
use temporalio_macros::activities;
use temporalio_sdk::activities::{ActivityContext, ActivityError};
use uuid::Uuid;

pub struct ProvisioningActivities {
    pub app: App,
}
#[activities]
impl ProvisioningActivities {
    #[activity(name = "ProvisionWorkspaceBucket")]
    pub async fn bucket(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::BucketInput,
    ) -> Result<Bucket, ActivityError> {
        provisioning::bucket(&self.app.pool, input)
            .await
            .map_err(activity_error)
    }
    #[activity(name = "ProvisionWorkspaceFilesystem")]
    pub async fn filesystem(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::FilesystemInput,
    ) -> Result<Filesystem, ActivityError> {
        provisioning::filesystem(&self.app.pool, input, self.app.config.max_nodes)
            .await
            .map_err(activity_error)
    }
    #[activity(name = "ReleaseWorkspaceProvisioning")]
    pub async fn release(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::Provisioned,
    ) -> Result<(), ActivityError> {
        provisioning::release(&self.app.pool, input)
            .await
            .map_err(activity_error)
    }
    #[activity(name = "FreezeWorkspaceBucket")]
    pub async fn freeze(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::BucketScope,
    ) -> Result<Uuid, ActivityError> {
        provisioning::freeze(&self.app.pool, input)
            .await
            .map_err(activity_error)
    }
    #[activity(name = "ListWorkspaceFilesystems")]
    pub async fn filesystems(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::FilesystemPage,
    ) -> Result<Vec<Uuid>, ActivityError> {
        provisioning::filesystems(&self.app.pool, input)
            .await
            .map_err(activity_error)
    }
    #[activity(name = "CompleteWorkspaceBucketDeletion")]
    pub async fn complete(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: provisioning::BucketScope,
    ) -> Result<(), ActivityError> {
        provisioning::complete(&self.app.pool, input)
            .await
            .map_err(activity_error)
    }
}
