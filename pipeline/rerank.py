import copy
import random

from .config import BaseConfig, Optional, PathConfig
from .docs import DocumentDatabaseFactory
from .pipeline import Task
from .retrieve import Results
from .util import ComponentFactory


class RerankInputConfig(BaseConfig):
    """Configuration of optional rerank inputs"""
    db: PathConfig
    results: Optional[PathConfig]


class RerankConfig(BaseConfig):
    """Configuration for the rerank task"""
    input: Optional[RerankInputConfig]
    name: str
    embedding: str
    save: str


class RerankFactory(ComponentFactory):
    classes = {
        'pacrr': 'MockReranker',
    }
    config_class = RerankConfig


class Reranker(Task):
    """Rerank interface"""

    def __init__(self, config):
        """
        Args:
            config (RerankConfig): Configuration parameters
        """
        super().__init__()
        self.config = config
        self.db = DocumentDatabaseFactory.create(config.input.db.path)

    def process(self, results):
        """Rerank query results

        Args:
            results (Results)

        Returns:
            Results
        """
        pass


class MockReranker(Reranker):
    """Mock reranker for testing"""

    def process(self, results):
        new_results = copy.copy(results.results)
        random.shuffle(new_results)
        return Results(results.query, 'MockReranker', new_results)
