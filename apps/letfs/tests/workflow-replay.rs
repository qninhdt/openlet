use letfs::temporal::{
    copy_workflow::CopyNode,
    lifecycle_workflow::{DeleteFilesystem, PurgeTrash, StorageMaintenance},
    process_file_workflow::ProcessFile,
};
use prost::Message;
use temporalio_common::protos::temporal::api::history::v1::{History, history_event::Attributes};
use temporalio_sdk::workflow_replayer::{WorkflowReplayer, WorkflowReplayerOptions};

#[tokio::test]
#[ignore = "requires current API histories; run the API suite then see docs/testing.md"]
async fn recorded_workflows_replay() {
    let directory = std::env::var("OPENLET_HISTORY_DIR").expect("OPENLET_HISTORY_DIR required");
    let replayer = WorkflowReplayer::new(
        WorkflowReplayerOptions::new()
            .register_workflow::<CopyNode>()
            .unwrap()
            .register_workflow::<PurgeTrash>()
            .unwrap()
            .register_workflow::<DeleteFilesystem>()
            .unwrap()
            .register_workflow::<ProcessFile>()
            .unwrap()
            .register_workflow::<StorageMaintenance>()
            .unwrap()
            .build(),
    )
    .unwrap();
    for name in [
        "CopyNodeContinued",
        "CopyNode",
        "CopyNodeRecovery",
        "PurgeTrash",
        "DeleteFilesystem",
        "StorageMaintenance",
        "ProcessFileParsed",
        "ProcessFileDirect",
        "ProcessFileFailed",
        "ProcessFileRecovery",
    ] {
        let bytes = std::fs::read(format!("{directory}/{name}.bin"))
            .unwrap_or_else(|error| panic!("generate {name} with the API suite first: {error}"));
        let history = History::decode(bytes.as_slice()).unwrap();
        let expected: Option<&[&str]> = match name {
            "ProcessFileParsed" | "ProcessFileRecovery" => {
                Some(&["process_file", "enrich_file", "index_file"])
            }
            "ProcessFileDirect" => Some(&["enrich_file", "index_file"]),
            "ProcessFileFailed" => Some(&["enrich_file"]),
            _ => None,
        };
        if let Some(expected) = expected {
            let scheduled = history
                .events
                .iter()
                .filter_map(|event| match &event.attributes {
                    Some(Attributes::ActivityTaskScheduledEventAttributes(a)) => Some(a),
                    _ => None,
                })
                .collect::<Vec<_>>();
            assert_eq!(
                scheduled
                    .iter()
                    .map(|a| a.activity_type.as_ref().unwrap().name.as_str())
                    .collect::<Vec<_>>(),
                expected,
                "{name}: activity order"
            );
            for activity in scheduled {
                let queue = if activity.activity_type.as_ref().unwrap().name == "process_file" {
                    "openlet-letfs-cpu"
                } else {
                    "openlet-letfs-io"
                };
                assert_eq!(activity.task_queue.as_ref().unwrap().name, queue, "{name}");
                assert_eq!(activity.retry_policy.as_ref().unwrap().maximum_attempts, 3);
                assert_eq!(activity.heartbeat_timeout.as_ref().unwrap().seconds, 30);
            }
        }
        replayer
            .replay_workflow(temporalio_client::WorkflowHistory::from(history))
            .await
            .unwrap_or_else(|error| panic!("{name}: {error}"));
    }
}
