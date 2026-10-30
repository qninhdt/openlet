use letfs::temporal::{
    copy_workflow::CopyNode,
    lifecycle_workflow::{DeleteFilesystem, PurgeTrash, StorageMaintenance},
    process_file_workflow::ProcessFile,
};
use prost::Message;
use temporalio_sdk::workflow_replayer::{WorkflowReplayer, WorkflowReplayerOptions};

#[tokio::test]
#[ignore = "requires real Temporal histories from make test-e2e TEST=all"]
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
            .register_workflow::<StorageMaintenance>()
            .unwrap()
            .build(),
    )
    .unwrap();
    for name in [
        "CopyNode",
        "CopyNodeFailed",
        "CopyNodeRecovery",
        "PurgeTrash",
        "DeleteFilesystem",
        "StorageMaintenance",
    ] {
        let data = std::fs::read(format!("{directory}/{name}.bin"))
            .expect("generate all history fixtures first");
        let history = temporalio_client::WorkflowHistory::from(
            temporalio_common::protos::temporal::api::history::v1::History::decode(data.as_slice())
                .unwrap(),
        );
        replayer
            .replay_workflow(history)
            .await
            .unwrap_or_else(|e| panic!("{name}: {e}"));
    }
}

#[tokio::test]
#[ignore = "requires real ProcessFile histories from make test-e2e TEST=processing"]
async fn process_file_history_replays() {
    replay_process_files(&[
        "ProcessFilePdf",
        "ProcessFileDocx",
        "ProcessFilePptx",
        "ProcessFileXlsx",
    ])
    .await;
}

#[tokio::test]
#[ignore = "requires actual kill/retry history from make test-e2e TEST=processing-recovery"]
async fn process_file_recovery_history_replays() {
    replay_process_files(&["ProcessFileRecovery", "ProcessFileExhausted"]).await;
}

async fn replay_process_files(names: &[&str]) {
    use temporalio_common::protos::temporal::api::history::v1::{
        History, history_event::Attributes,
    };
    let directory = std::env::var("OPENLET_HISTORY_DIR").expect("OPENLET_HISTORY_DIR required");
    let replayer = WorkflowReplayer::new(
        WorkflowReplayerOptions::new()
            .register_workflow::<ProcessFile>()
            .unwrap()
            .build(),
    )
    .unwrap();
    for name in names {
        let bytes = std::fs::read(format!("{directory}/{name}.bin"))
            .expect("generate processing histories first");
        let history = History::decode(bytes.as_slice()).unwrap();
        let scheduled = history
            .events
            .iter()
            .filter_map(|event| match &event.attributes {
                Some(Attributes::ActivityTaskScheduledEventAttributes(a)) => Some(a),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(scheduled.len(), 1);
        assert_eq!(
            scheduled[0].activity_type.as_ref().unwrap().name,
            "process_file"
        );
        assert_eq!(
            scheduled[0].task_queue.as_ref().unwrap().name,
            "openlet-letfs-processing"
        );
        replayer
            .replay_workflow(temporalio_client::WorkflowHistory::from(history))
            .await
            .unwrap_or_else(|e| panic!("{name}: {e}"));
    }
}

#[tokio::test]
#[ignore = "requires actual ExportArchive history from make test-e2e TEST=zip-export"]
async fn export_archive_history_replays() {
    use letfs::temporal::export_archive_workflow::ExportArchive;
    use temporalio_common::protos::temporal::api::history::v1::{
        History, history_event::Attributes,
    };
    let directory = std::env::var("OPENLET_HISTORY_DIR").expect("OPENLET_HISTORY_DIR required");
    let replayer = WorkflowReplayer::new(
        WorkflowReplayerOptions::new()
            .register_workflow::<ExportArchive>()
            .unwrap()
            .build(),
    )
    .unwrap();
    for name in ["ExportArchive", "ExportArchiveRetry"] {
        let bytes = std::fs::read(format!("{directory}/{name}.bin"))
            .expect("generate actual export history first");
        let history = History::decode(bytes.as_slice()).unwrap();
        let activities = history
            .events
            .iter()
            .filter_map(|event| match &event.attributes {
                Some(Attributes::ActivityTaskScheduledEventAttributes(a)) => Some(a),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(activities.len(), 1);
        assert_eq!(
            activities[0].activity_type.as_ref().unwrap().name,
            "ArchiveActivities::export_archive"
        );
        replayer
            .replay_workflow(temporalio_client::WorkflowHistory::from(history))
            .await
            .unwrap();
    }
}
