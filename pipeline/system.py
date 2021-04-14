import logging
import pathlib

from .config import BaseConfig, ConfigService
from .docs import DocumentsConfig, DocumentStoreConfig, DocumentProcessorFactory, DocumentReaderFactory, \
    DocumentStore, DocWriter
from .error import PipelineError
from .index import IndexConfig, IndexerFactory
from .pipeline import Pipeline
from .rerank import RerankConfig, RerankFactory
from .retrieve import JsonResultsWriter, JsonResultsReader, TrecResultsWriter, RetrieveConfig, RetrieverFactory
from .score import QrelsReaderFactory, ScoreConfig, Scorer
from .topics import TopicProcessorFactory, TopicReaderFactory, TopicsConfig, QueryReader, QueryWriter
from .util.file import delete_dir, is_complete

LOGGER = logging.getLogger(__name__)


class RunConfig(BaseConfig):
    """Configuration for a run of the system"""
    path: str
    documents: DocumentsConfig
    document_store: DocumentStoreConfig
    topics: TopicsConfig
    index: IndexConfig
    retrieve: RetrieveConfig
    rerank: RerankConfig
    score: ScoreConfig


class System:
    def __init__(self, config_filename, verbose=False, overrides=None):
        self.setup_logging(verbose)

        config_service = ConfigService(overrides)
        conf_dict = config_service.read_config(config_filename)
        self.prepare_config(conf_dict)
        conf = RunConfig(**conf_dict)

        if is_complete(conf.index.save) and not is_complete(conf.document_store.path):
            raise PipelineError("Cannot run with a complete index and incomplete doc store")
        if not is_complete(conf.document_store.path) and pathlib.Path(conf.document_store.path).exists():
            delete_dir(conf.document_store.path)
        readonly = True if is_complete(conf.document_store.path) else False
        doc_store = DocumentStore(conf.document_store.path, readonly)
        self.stage1 = self.build_phase1_pipeline(conf, doc_store)
        self.stage2 = self.build_phase2_pipeline(conf, doc_store)

    def run(self):
        if self.stage1:
            LOGGER.info("Stage 1 pipeline: %s", self.stage1)
        else:
            LOGGER.info("Stage 1 already complete")
        LOGGER.info("Stage 2 pipeline: %s", self.stage2)

        if self.stage1:
            LOGGER.info("Starting processing of documents")
            self.stage1.run()
            LOGGER.info("Ingested %s documents", self.stage1.count)

        LOGGER.info("Starting processing of topics")
        self.stage2.run()
        LOGGER.info("Processed %s topics", self.stage2.count)

    def build_phase1_pipeline(self, conf, doc_store):
        if is_complete(conf.index.save):
            return None
        elif pathlib.Path(conf.index.save).exists():
            delete_dir(conf.index.save)
        iterable = DocumentReaderFactory.create(conf.documents.input)
        tasks = [DocumentProcessorFactory.create(conf.documents.process, doc_store)]
        if conf.documents.save is not False:
            tasks.append(DocWriter(conf.documents.save))
        tasks.append(IndexerFactory.create(conf.index))
        return Pipeline(tasks, iterable)

    def build_phase2_pipeline(self, conf, doc_store):
        iterable = TopicReaderFactory.create(conf.topics.input)
        tasks = [TopicProcessorFactory.create(conf.topics.process)]
        tasks, iterable = self.add_io_task(tasks, iterable, conf.topics.save, QueryReader, QueryWriter)
        tasks.append(RetrieverFactory.create(conf.retrieve))
        tasks, iterable = self.add_io_task(tasks, iterable, conf.retrieve.save, JsonResultsReader, JsonResultsWriter)
        tasks.append(RerankFactory.create(conf.rerank, doc_store))
        if is_complete(conf.rerank.save):
            raise PipelineError("Rerank results already complete")
        elif pathlib.Path(conf.rerank.save).exists():
            delete_dir(conf.rerank.save)
        tasks.append(TrecResultsWriter(conf.rerank.save))
        qrels = QrelsReaderFactory.create(conf.score.input).read()
        tasks.append(Scorer(conf.score, qrels))
        return Pipeline(tasks, iterable)

    def add_io_task(self, tasks, iterable, path, reader, writer):
        if path is not False:
            if is_complete(path):
                tasks = []
                iterable = reader(path)
            else:
                if pathlib.Path(path).exists():
                    delete_dir(path)
                tasks.append(writer(path))
        return tasks, iterable

    @staticmethod
    def setup_logging(verbose):
        log_level = logging.DEBUG if verbose else logging.INFO
        logger = logging.getLogger('pipeline')
        logger.setLevel(log_level)
        console = logging.StreamHandler()
        console.setLevel(log_level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console.setFormatter(formatter)
        logger.addHandler(console)

    @staticmethod
    def prepare_config(conf):
        base = pathlib.Path(conf['path'])
        # set path for components to be under the base directory of run
        for c in conf.values():
            if isinstance(c, dict):
                if 'save' in c and not isinstance(c['save'], bool):
                    c['save'] = str(base / c['save'])
        conf['document_store']['path'] = str(base / conf['document_store']['path'])
        # if input to retrieve is not set, we grab it from index
        if 'input' not in conf['retrieve']:
            conf['retrieve']['input'] = {'path': conf['index']['save']}
