# Copyright (c) 2020 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

from typing import Optional
import unittest
import unittest.mock

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

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        self._log_terminate()


class Forever(task_lib.Task):
    def __init__(self):
        super().__init__(title="Forever", forever=True)

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        self._terminated.wait()
        self._log_terminate()


class PrematureTerminator(task_lib.Task):
    def __init__(self):
        # NB: Not marked as forever
        super().__init__(title="Premature terminator")

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        pass


class Failer(task_lib.Task):
    def __init__(self):
        super().__init__(title="Failer")

    def _terminate(self) -> None:
        pass

    def _run(self) -> None:
        raise FailerException()


class Fundamentals(unittest.TestCase):
    def setUp(self) -> None:
        self.task: task_lib.Task = Bounded()

    def runs_forever(self) -> bool:
        return False

    def test_is_alive(self) -> None:
        self.assertFalse(self.task.is_alive())
        self.task.start()
        if self.runs_forever():
            self.assertTrue(self.task.is_alive())
            self.task.terminate()
        self.task.join()
        self.assertFalse(self.task.is_alive())

    def test_callback(self) -> None:
        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(callback)

        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback.assert_called_once_with(self.task)

    def test_failer_callback(self) -> None:
        def failer(_) -> None:
            raise FailerCallbackException()

        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(failer)
        self.task.add_done_callback(callback)

        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback.assert_called_once_with(self.task)

    def test_callback_already_done(self) -> None:
        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        callback = unittest.mock.MagicMock()
        self.task.add_done_callback(callback)
        callback.assert_called_once_with(self.task)

    def test_failer_callback_already_done(self) -> None:
        self.task.start()
        if self.runs_forever():
            self.task.terminate()
        self.task.join()

        def failer(_) -> None:
            raise FailerCallbackException()

        # Shouldn't raise an exception
        self.task.add_done_callback(failer)


def run_and_terminate_idempotent(
    task: task_lib.Task, exception: Optional[Exception]
) -> None:
    task.terminate(exception)
    task.terminate(exception)
    task.join()
    task.join()
    task.terminate(exception)
    task.terminate(exception)
    task.result()
    task.result()


class NormalTerminationTests(Fundamentals):
    def test_terminate(self) -> None:
        self.task.start()
        run_and_terminate_idempotent(self.task, None)
        self.assertEqual(self.task.exception(), None)

    def test_terminate_exception(self) -> None:
        self.task.start()
        exc = ExternalTerminateException()
        with self.assertRaises(ExternalTerminateException):
            run_and_terminate_idempotent(self.task, exc)
        self.assertEqual(self.task.exception(), exc)


class ForeverTest(NormalTerminationTests):
    def setUp(self) -> None:
        self.task: Forever = Forever()

    def runs_forever(self) -> bool:
        return True


class BoundedTest(NormalTerminationTests):
    def setUp(self) -> None:
        self.task: task_lib.Task = Bounded()

    def runs_forever(self) -> bool:
        return False

    def test_natural_end(self) -> None:
        self.task.start()
        self.task.result()
        run_and_terminate_idempotent(self.task, None)
        self.assertEqual(self.task.exception(), None)


class AbnormalTerminationTests(Fundamentals):

    expected_exc_type = Exception

    def setUp(self) -> None:
        self.task: task_lib.Task = Failer()

    def runs_forever(self) -> bool:
        return False

    def test_natural_abnormal_termination(self) -> None:
        self.task.start()
        # NB: don't terminate
        self.task.join()
        self.task.join()
        with self.assertRaises(self.expected_exc_type):
            self.task.result()
        self.assertIsInstance(self.task.exception(), self.expected_exc_type)


class FailerTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self) -> None:
        self.task: task_lib.Task = Failer()


class PrematureTerminatorTest(AbnormalTerminationTests):

    expected_exc_type = task_lib.PrematureTermination

    def setUp(self) -> None:
        self.task: task_lib.Task = PrematureTerminator()


class FailerTerminatesChildTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self) -> None:
        self.task: task_lib.Task = Failer()
        self.child = Forever()
        self.task._add_child(self.child)

    def test_terminate_child(self) -> None:
        self.task.start()
        self.task.join()
        # Should be terminated, but no exception
        self.child.result()


class ForeverStartChildren(Forever):
    def _run(self) -> None:
        for child in self._get_children():
            child.start()
        super()._run()


class FailerTerminatesParentTest(AbnormalTerminationTests):

    expected_exc_type = FailerException

    def setUp(self) -> None:
        self.task: task_lib.Task = ForeverStartChildren()
        self.child = Failer()
        self.task._add_child(self.child, start=False)


class CatchChildErrorsTest(NormalTerminationTests):
    def setUp(self) -> None:
        self.task: task_lib.Task = ForeverStartChildren()
        self.child = Failer()
        self.task._add_child(
            self.child, start=False, terminate_me_on_error=False
        )

    def runs_forever(self) -> bool:
        return True
