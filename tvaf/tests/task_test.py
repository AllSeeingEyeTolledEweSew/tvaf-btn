import unittest
import unittest.mock
from typing import Optional

from tvaf import task as task_lib


class FailerException(Exception):
    pass


class FailerCallbackException(Exception):
    pass


class ExternalTerminateException(Exception):
    pass


class Bounded(task_lib.Task):

    def __init__(self):
        super().__init__(title="Bounded", forever=False)

    def _terminate(self):
        pass

    def _run(self):
        self._log_terminate()


class Forever(task_lib.Task):

    def __init__(self):
        super().__init__(title="Forever", forever=True)

    def _terminate(self):
        pass

    def _run(self):
        self._terminated.wait()
        self._log_terminate()


class PrematureTerminator(task_lib.Task):

    def __init__(self):
        # NB: Not marked as forever
        super().__init__(title="Premature terminator")

    def _terminate(self):
        pass

    def _run(self):
        pass


class Failer(task_lib.Task):

    def __init__(self):
        super().__init__(title="Failer")

    def _terminate(self):
        pass

    def _run(self):
        raise FailerException()


class Fundamentals(unittest.TestCase):

    def setUp(self):
        self.task = Bounded()

    def runs_forever(self) -> bool:  # pylint: disable=no-self-use
        return False

    def test_is_alive(self):
        self.assertFalse(self.task.is_alive())
        self.task.start()
        if self.runs_forever():
            self.assertTrue(self.task.is_alive())
            self.task.terminate()
        self.task.join()
        self.assertFalse(self.task.is_alive())

    def test_callback(self):
        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(callback)

        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback.assert_called_once_with(self.task)

    def test_failer_callback(self):

        def failer(_):
            raise FailerCallbackException()

        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(failer)
        self.task.add_done_callback(callback)

        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback.assert_called_once_with(self.task)

    def test_callback_already_done(self):
        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(callback)
        callback.assert_called_once_with(self.task)

    def test_failer_callback_already_done(self):
        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        def failer(_):
            raise FailerCallbackException()

        # Shouldn't raise an exception
        self.task.add_done_callback(failer)


def run_and_terminate_idempotent(task: task_lib.Task,
                                 exception: Optional[Exception]):
    task.terminate(exception)
    task.terminate(exception)
    task.join()
    task.join()
    task.terminate(exception)
    task.terminate(exception)
    task.result()
    task.result()


class NormalTerminationTests(Fundamentals):

    def test_terminate(self):
        self.task.start()
        run_and_terminate_idempotent(self.task, None)
        self.assertEqual(self.task.exception(), None)

    def test_terminate_exception(self):
        self.task.start()
        exc = ExternalTerminateException()
        with self.assertRaises(ExternalTerminateException):
            run_and_terminate_idempotent(self.task, exc)
        self.assertEqual(self.task.exception(), exc)


class ForeverTest(NormalTerminationTests):

    def setUp(self):
        self.task = Forever()

    def runs_forever(self):
        return True


class BoundedTest(NormalTerminationTests):

    def setUp(self):
        self.task = Bounded()

    def runs_forever(self):
        return False

    def test_natural_end(self):
        self.task.start()
        self.task.result()
        run_and_terminate_idempotent(self.task, None)
        self.assertEqual(self.task.exception(), None)


class AbnormalTerminationTests(Fundamentals):

    expected_exc_type = Exception

    def setUp(self):
        self.task = Failer()

    def runs_forever(self):
        return False

    def test_natural_abnormal_termination(self):
        self.task.start()
        # NB: don't terminate
        self.task.join()
        self.task.join()
        with self.assertRaises(self.expected_exc_type):
            self.task.result()
        self.assertIsInstance(self.task.exception(), self.expected_exc_type)


class FailerTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self):
        self.task = Failer()


class PrematureTerminatorTest(AbnormalTerminationTests):

    expected_exc_type = task_lib.PrematureTermination

    def setUp(self):
        self.task = PrematureTerminator()


class FailerTerminatesChildTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self):
        self.task = Failer()
        self.child = Forever()
        # pylint: disable=protected-access
        self.task._add_child(self.child)

    def test_terminate_child(self):
        self.task.start()
        self.task.join()
        # Should be terminated, but no exception
        self.child.result()


class ForeverStartChildren(Forever):

    def _run(self):
        for child in self._get_children():
            child.start()
        super()._run()


class FailerTerminatesParentTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self):
        self.task = ForeverStartChildren()
        self.child = Failer()
        # pylint: disable=protected-access
        self.task._add_child(self.child, start=False)


class CatchChildErrorsTest(NormalTerminationTests):

    def setUp(self):
        self.task = ForeverStartChildren()
        self.child = Failer()
        # pylint: disable=protected-access
        self.task._add_child(self.child,
                             start=False,
                             terminate_me_on_error=False)

    def runs_forever(self):
        return True
