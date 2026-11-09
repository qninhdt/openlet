from temporalio import workflow


@workflow.defn
class MessagePassingFixture:
    def __init__(self):
        self.message = ""

    @workflow.update
    async def receive(self, message: str) -> str:
        self.message = message
        return message

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: bool(self.message))
        assert workflow.info().get_current_history_length() > 0
        workflow.info().is_continue_as_new_suggested()
        return self.message
