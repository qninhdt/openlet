"""Additional real SQL workloads for sql-benchmark.py's disposable fixtures."""


def audit(read, bench, sql, scope, fs, uid, lit, bind, cols):
    base = "apps/letfs/internal/filesystem/"

    def case(label, file, needle, args=(), db="letfs"):
        bench(label, bind(read(file, needle), args), db)

    zero = lit("00000000-0000-0000-0000-000000000000")
    backfill = read(base + "backfill.go", "publication_status!='ready'")
    for mode in ("missing", "rebuild-index"):
        for label, after in (
            ("first", zero),
            ("late", lit("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")),
        ):
            bench(
                "backfill-" + mode + "-" + label,
                backfill,
                modes=("force_custom_plan", "force_generic_plan"),
                types="uuid,text,int",
                args=[after, lit(mode), "101"],
            )
    sql(
        "UPDATE files SET publication_status='pending' WHERE node_id IN (SELECT node_id FROM files ORDER BY node_id LIMIT 100); ANALYZE files;",
        "letfs",
    )
    bench(
        "backfill-missing-sparse",
        backfill,
        modes=("force_custom_plan", "force_generic_plan"),
        types="uuid,text,int",
        args=[zero, lit("missing"), "101"],
    )
    case(
        "processing-dispatch",
        base + "processing_control.go",
        "WHERE scopeID.state='active'",
    )
    for root in (5000, 2):
        case(
            "archive-" + str(root),
            base + "archive.go",
            "SELECT n.*,''::text",
            [lit(scope), lit(uid(root)), "10002"],
        )
    inventory = (
        read(base + "enrichment.go", "SELECT n.*,''::text")
        + cols
        + read(
            base + "enrichment.go",
            ",false,n.path,COALESCE(f.inline_bytes,convert_to(f.text_content,'UTF8')),f.object_key",
        )
    )
    bench("processing-inventory", bind(inventory, [lit(uid(5000)), lit(scope), "1002"]))
    case(
        "purge-descend",
        base + "deletion.go",
        "WITH RECURSIVE branch AS",
        [lit(uid(2)), lit(scope)],
    )
    case(
        "purge-leaf-siblings",
        base + "deletion.go",
        "(n.id=$2 OR n.parent_id=$3)",
        [lit(scope), lit(uid(50001)), lit(uid(5000))],
    )
    case("expire-uploads", base + "maintenance.go", "SELECT id,scope_id FROM uploads")
    case(
        "multipart-cleanup",
        base + "maintenance.go",
        "SELECT id,candidate_key,multipart_id",
    )
    case(
        "upload-capacity",
        base + "uploads.go",
        "SELECT count(*) FROM uploads u JOIN scopes",
        [lit(fs)],
    )
    case(
        "archive-current-payload",
        base + "archive.go",
        "WITH RECURSIVE ancestors AS",
        [lit(uid(50001)), lit(scope), lit(uid(2))],
    )
    case(
        "move-transfer-subtree",
        base + "scope_move.go",
        "false AS derived",
        [lit(uid(2)), lit(scope)],
    )
    case("discard-detached", base + "artifacts.go", "SELECT n.id,n.scope_id FROM nodes")
    case(
        "receipt-prune",
        base + "provisioning.go",
        "DELETE FROM idempotency_keys WHERE (scope,operation,request_key)",
    )

    # Many unrelated scopes with terminal uploads: pending-only indexes cannot serve cleanup.
    sql(
        f"""BEGIN;
    INSERT INTO filesystems(id,limit_bytes) SELECT md5('audit-fs-'||i)::uuid,100000000 FROM generate_series(1,1000) i;
    INSERT INTO scopes(id,filesystem_id,root_id) SELECT md5('audit-scope-'||i)::uuid,md5('audit-fs-'||i)::uuid,md5('audit-root-'||i)::uuid FROM generate_series(1,1000) i;
    INSERT INTO nodes(id,scope_id,name,kind) SELECT md5('audit-root-'||i)::uuid,md5('audit-scope-'||i)::uuid,'root','directory' FROM generate_series(1,1000) i;
    INSERT INTO uploads(id,scope_id,actor_id,actor_kind,input,transport,expected_size,state) SELECT md5('audit-upload-'||i)::uuid,md5('audit-scope-'||((i-1)/100+1))::uuid,md5('actor')::uuid,'user','{{}}','inline',1,'aborted' FROM generate_series(1,100000) i;
    INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) SELECT 'audit/'||i,'create-upload',i::text,'hash',jsonb_build_object('id',md5('audit-upload-'||((i-1)*100+1))::uuid) FROM generate_series(1,1000) i;
    INSERT INTO object_deletions(object_key,filesystem_id,state,eligible_at) SELECT 'audit-deleted-'||i,md5('audit-fs-'||((i-1)/100+1))::uuid,'deleted',now()-interval '1 day' FROM generate_series(1,100000) i;
    INSERT INTO object_deletions(object_key,filesystem_id,state,eligible_at) SELECT 'audit-pending-'||i,'{fs}','pending',now()-interval '1 hour' FROM generate_series(1,100) i;
    INSERT INTO index_deletions(file_id,generation,eligible_at) SELECT md5('node-'||i)::uuid,1,now()-interval '1 hour' FROM generate_series(10001,100000) i;
    INSERT INTO trash_entries(id,scope_id,node_id,original_parent_id,original_name,actor_id,actor_kind) SELECT md5('audit-trash-'||i)::uuid,'{scope}',md5('node-'||i)::uuid,md5('parent-'||i)::uuid,'trashed',md5('actor')::uuid,'user' FROM generate_series(2,100000) i;
    COMMIT; ANALYZE;""",
        "letfs",
    )
    sql(
        f"INSERT INTO uploads(id,scope_id,actor_id,actor_kind,input,transport,expected_size) SELECT md5('audit-user-upload-'||i)::uuid,'{scope}',md5('actor')::uuid,'user','{{}}','inline',1 FROM generate_series(1,1000) i; ANALYZE uploads;",
        "letfs",
    )
    case(
        "upload-capacity-mixed",
        base + "uploads.go",
        "SELECT count(*) FROM uploads u JOIN scopes",
        [lit(fs)],
    )
    target_scope = "md5('audit-scope-500')::uuid"
    target_fs = "md5('audit-fs-500')::uuid"
    case(
        "scope-abort-upload",
        base + "deletion.go",
        "UPDATE uploads SET state=CASE",
        [target_scope],
    )
    case(
        "scope-queue-candidates",
        base + "deletion.go",
        "SELECT candidate_key,$2,true",
        [target_scope, target_fs],
    )
    case(
        "scope-upload-receipts",
        base + "deletion.go",
        "UPDATE idempotency_keys r",
        [target_scope],
    )
    case(
        "scope-prune-uploads",
        base + "provisioning.go",
        "DELETE FROM uploads WHERE scope_id",
        [target_scope],
    )
    bench(
        "scope-upload-exists",
        bind("SELECT EXISTS(SELECT 1 FROM uploads WHERE scope_id=$1)", [target_scope]),
    )
    case(
        "filesystem-prune-objects",
        base + "provisioning.go",
        "DELETE FROM object_deletions WHERE filesystem_id",
        [target_fs],
    )
    bench(
        "filesystem-object-exists",
        bind(
            "SELECT EXISTS(SELECT 1 FROM object_deletions WHERE filesystem_id=$1)",
            [target_fs],
        ),
    )
    case(
        "object-cleanup-due",
        base + "maintenance.go",
        "SELECT object_key,filesystem_id FROM object_deletions",
    )
    case(
        "object-cleanup-claim",
        base + "maintenance.go",
        "UPDATE object_deletions d SET state",
        [lit("audit-pending-50")],
    )
    case(
        "index-cleanup-dense-ready",
        base + "index_cleanup.go",
        "SELECT d.file_id,d.generation FROM index_deletions",
    )
    case(
        "trash-clear-parent",
        base + "deletion.go",
        "UPDATE trash_entries SET original_parent_id",
        [lit(scope), "ARRAY[md5('parent-50000')::uuid]"],
    )
    trash_columns = read(
        base + "trash.go",
        "id,node_id,original_parent_id,original_name,actor_id,state,created_at,actor_kind",
    )
    bench(
        "trash-page",
        bind(
            "SELECT "
            + trash_columns
            + " FROM trash_entries WHERE scope_id=$1 AND id>$2 ORDER BY id LIMIT $3",
            [lit(scope), zero, "51"],
        ),
    )
    for file, needle, label in (
        (
            "provisioning.go",
            "SELECT id FROM scopes WHERE state='deleted'",
            "prune-deleted-scopes",
        ),
        (
            "provisioning.go",
            "SELECT id FROM filesystems WHERE state='deleted'",
            "prune-deleted-filesystems",
        ),
    ):
        case(label, base + file, needle)
    case(
        "reconcile-filesystems",
        "apps/letfs/internal/temporal/maintenance.go",
        "SELECT id FROM filesystems",
    )
    case(
        "reconcile-scopes",
        "apps/letfs/internal/temporal/maintenance.go",
        "SELECT sc.filesystem_id,sc.id",
    )

    wsbase = "apps/workspace/internal/workspace/"
    sql(
        """INSERT INTO workspace_invitations(id,workspace_id,email,role,token_hash,expires_at)
    SELECT md5('invite-'||i)::uuid,md5('ws-'||((i-1)/10+1))::uuid,'member-'||i||'@example.test','member',decode(md5('token-'||i)||md5('token2-'||i),'hex'),now()+interval '1 day' FROM generate_series(1,100000) i;
    INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id,expires_at)
    SELECT md5('actor-'||i)::uuid,md5('key-'||i)::uuid,'hash',md5('ws-'||((i-1)/10+1))::uuid,now()+CASE WHEN i%1000=0 THEN interval '-1 hour' ELSE interval '1 day' END FROM generate_series(1,100000) i; ANALYZE;""",
        "workspace",
    )
    ws = "md5('ws-500')::uuid"
    for file, needle, label, args in (
        ("membership.go", "SELECT count(*)", "workspace-member-count", [ws]),
        (
            "relations.go",
            "SELECT personal_scope_id",
            "workspace-remove-relationships",
            [ws],
        ),
        (
            "relations.go",
            "SELECT user_id FROM workspace_members",
            "workspace-rebuild-member-page",
            [ws, zero],
        ),
        (
            "invitations.go",
            "SELECT id,workspace_id,email,role,status,expires_at FROM workspace_invitations WHERE workspace_id=$1 AND id>",
            "workspace-invitation-page",
            [ws, zero, "51"],
        ),
        (
            "invitations.go",
            "WHERE token_hash=$1",
            "workspace-invitation-token",
            ["decode(md5('token-500')||md5('token2-500'),'hex')"],
        ),
        (
            "deletion.go",
            "DELETE FROM workspace_invitations",
            "workspace-delete-invitations",
            [ws],
        ),
        (
            "maintenance.go",
            "DELETE FROM idempotency_keys",
            "workspace-receipt-prune",
            [],
        ),
        (
            "relations.go",
            "SELECT id FROM workspaces WHERE id>",
            "workspace-rebuild-page",
            [zero],
        ),
    ):
        case(label, wsbase + file, needle, args, "workspace")

    # Capture the write cost of the cleanup indexes on the same additional fixture.
    bench(
        "insert-1000-terminal-uploads",
        f"INSERT INTO uploads(id,scope_id,actor_id,actor_kind,input,transport,expected_size,state) SELECT md5('audit-write-upload-'||i)::uuid,{target_scope},md5('actor')::uuid,'user','{{}}','inline',1,'aborted' FROM generate_series(1,1000) i",
    )
    bench(
        "insert-1000-object-tombstones",
        f"INSERT INTO object_deletions(object_key,filesystem_id,state) SELECT 'audit-write-object-'||i,{target_fs},'deleted' FROM generate_series(1,1000) i",
    )
    bench(
        "insert-1000-trash",
        f"INSERT INTO trash_entries(id,scope_id,node_id,original_parent_id,original_name,actor_id,actor_kind) SELECT md5('audit-write-trash-'||i)::uuid,'{scope}',md5('node-'||i)::uuid,md5('parent-'||i)::uuid,'trashed',md5('actor')::uuid,'user' FROM generate_series(100001,101000) i",
    )
