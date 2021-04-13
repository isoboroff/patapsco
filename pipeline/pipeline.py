import abc
import logging

LOGGER = logging.getLogger(__name__)


class Task(abc.ABC):
    """A task in a pipeline

    Implementations must define a process() method.
    Any initialization or cleanup can be done in begin() or end().
    See Pipeline for how to construct a pipeline of tasks.
    """

    def __init__(self):
        self.downstream = None

    @abc.abstractmethod
    def process(self, item):
        """Process an item

        A task must implement this method.
        It must return a new item that resulted from processing or the original item.
        """
        pass

    def begin(self):
        """Optional begin method for initialization"""
        pass

    def end(self):
        """Optional end method for cleaning up"""
        pass

    def _process(self, item):
        """Push the output of process() to the next task"""
        item = self.process(item)
        if self.downstream:
            self.downstream._process(item)

    def _begin(self):
        self.begin()
        if self.downstream:
            self.downstream._begin()

    def _end(self):
        self.end()
        if self.downstream:
            self.downstream._end()


class Pipeline:
    def __init__(self, tasks, iterable):
        self.task = self._connect(tasks)
        self.iterable = iterable
        self.count = 0

    def run(self):
        self.begin()
        for item in self.iterable:
            self.task._process(item)
            self.count += 1
        self.end()

    def begin(self):
        self.count = 0
        self.task._begin()

    def end(self):
        self.task._end()

    def _connect(self, tasks):
        head_task = prev_task = tasks.pop(0)
        while tasks:
            cur_task = tasks.pop(0)
            prev_task.downstream = cur_task
            prev_task = cur_task
        return head_task

    def __str__(self):
        task_names = [str(self.iterable.__class__.__name__)]
        task = self.task
        while task:
            task_names.append(str(task.__class__.__name__))
            task = task.downstream
        return ' | '.join(task_names)
