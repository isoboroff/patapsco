import csv
import dataclasses
import json
import pathlib

from .config import BaseConfig, ConfigService, PathConfig, Optional, Union
from .error import ConfigError, ParseError
from .pipeline import Task
from .text import TextProcessor, StemConfig, TokenizeConfig, TruncStemConfig
from .util import trec, ComponentFactory, DataclassJSONEncoder
from .util.file import GlobFileGenerator, touch_complete


@dataclasses.dataclass
class Topic:
    id: str
    lang: str
    title: str
    desc: Optional[str]
    narr: Optional[str]


@dataclasses.dataclass
class Query:
    id: str
    lang: str
    text: str


class TopicsInputConfig(BaseConfig):
    """Configuration for Topic input"""
    format: str
    lang: str
    encoding: str = "utf8"
    strip_non_digits: bool = False
    prefix: Union[bool, str] = "EN-"
    path: Union[str, list]


class TopicsConfig(BaseConfig):
    """Configuration for topics task"""
    input: TopicsInputConfig
    fields: str = "title"  # field1+field2 where field is title, desc, or narr
    output: Union[bool, PathConfig]


class QueriesInputConfig(BaseConfig):
    """Configuration for reading queries"""
    format: str = "json"
    encoding: str = "utf8"
    path: Union[str, list]


class ProcessorConfig(BaseConfig):
    """Configuration of the topic processor"""
    char_normalize: bool = True
    lowercase: bool = True
    tokenize: TokenizeConfig
    stem: Union[StemConfig, TruncStemConfig]


class QueriesConfig(BaseConfig):
    """Configuration for processing queries"""
    input: Optional[QueriesInputConfig]
    process: ProcessorConfig
    output: Union[bool, PathConfig]


class TopicReaderFactory(ComponentFactory):
    classes = {
        'sgml': 'SgmlTopicReader',
        'xml': 'XmlTopicReader',
        'json': 'JsonTopicReader',
        'msmarco': 'TsvTopicReader'
    }
    config_class = TopicsInputConfig


class TopicProcessor(Task):
    """Topic Preprocessing"""

    FIELD_MAP = {
        'title': 'title',
        'name': 'title',
        'desc': 'desc',
        'description': 'desc',
        'narr': 'narr',
        'narrative': 'narr'
    }

    def __init__(self, config):
        """
        Args:
            config (TopicsConfig)
        """
        super().__init__()
        self.fields = self._extract_fields(config.fields)

    def process(self, topic):
        """
        Args:
            topic (Topic)

        Returns
            Query
        """
        text = ' '.join([getattr(topic, f).strip() for f in self.fields])
        return Query(topic.id, topic.lang, text)

    @classmethod
    def _extract_fields(cls, fields_str):
        fields = fields_str.split('+')
        try:
            return [cls.FIELD_MAP[f.lower()] for f in fields]
        except KeyError as e:
            raise ConfigError(f"Unrecognized topic field: {e}")


class SgmlTopicReader:
    """Iterator over topics from trec sgml"""

    def __init__(self, config):
        self.lang = config.lang
        self.strip_non_digits = config.strip_non_digits
        prefix = config.prefix
        self.topics = GlobFileGenerator(config.path, trec.parse_sgml_topics, prefix, config.encoding)

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        identifier = ''.join(filter(str.isdigit, topic[0])) if self.strip_non_digits else topic[0]
        return Topic(identifier, self.lang, topic[1], topic[2], topic[3])


class XmlTopicReader:
    """Iterator over topics from trec xml"""

    def __init__(self, config):
        self.lang = config.lang
        self.strip_non_digits = config.strip_non_digits
        self.topics = GlobFileGenerator(config.path, trec.parse_xml_topics, config.encoding)

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        identifier = ''.join(filter(str.isdigit, topic[0])) if self.strip_non_digits else topic[0]
        return Topic(identifier, topic[1], topic[2], topic[3], topic[4])


class JsonTopicReader:
    """Iterator over topics from jsonl file """

    def __init__(self, config):
        self.lang = config.lang
        self.topics = GlobFileGenerator(config.path, self.parse, config.encoding)

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        return Topic(topic[0], self.lang, topic[1], topic[2], None)

    @staticmethod
    def parse(path, encoding='utf8'):
        with open(path, 'r', encoding=encoding) as fp:
            for line in fp:
                try:
                    data = json.loads(line.strip())
                except json.decoder.JSONDecodeError as e:
                    raise ParseError(f"Problem parsing json from {path}: {e}")
                try:
                    title = data['topic_name'].strip()
                    desc = data['topic_description'].strip()
                    yield data['topic_id'], title, desc
                except KeyError as e:
                    raise ParseError(f"Missing field {e} in json docs element: {data}")


class TsvTopicReader:
    """Iterator over topics from tsv file """

    def __init__(self, config):
        self.lang = config.lang
        self.topics = GlobFileGenerator(config.path, self.parse, config.encoding)

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        return Topic(topic[0], self.lang, topic[1], None, None)

    @staticmethod
    def parse(path, encoding='utf8'):
        with open(path, 'r', encoding=encoding) as fp:
            reader = csv.reader(fp, delimiter='\t')
            for line in reader:
                yield line[0], line[1].strip()


class QueryWriter(Task):
    """Write queries to a jsonl file"""

    def __init__(self, path, config):
        """
        Args:
            path (str): Path of query file to write.
        """
        super().__init__()
        self.dir = pathlib.Path(path)
        self.dir.mkdir(parents=True)
        path = self.dir / 'queries.jsonl'
        self.file = open(path, 'w')
        self.config = config
        self.config_path = self.dir / 'config.yml'

    def process(self, query):
        """
        Args:
            query (Query)

        Returns
            Query
        """
        self.file.write(json.dumps(query, cls=DataclassJSONEncoder) + "\n")
        return query

    def end(self):
        self.file.close()
        ConfigService.write_config_file(self.config_path, self.config)
        touch_complete(self.dir)


class QueryReader:
    """Iterator over queries from jsonl file """

    def __init__(self, path):
        path = pathlib.Path(path) / 'queries.jsonl'
        with open(path) as fp:
            self.data = fp.readlines()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return Query(**json.loads(self.data.pop(0)))
        except IndexError:
            raise StopIteration()


class QueryProcessor(Task, TextProcessor):
    """Query Preprocessing"""

    def __init__(self, config):
        """
        Args:
            config (ProcessorConfig)
        """
        Task.__init__(self)
        TextProcessor.__init__(self, config)

    def process(self, query):
        """
        Args:
            query (Query)

        Returns
            Query
        """
        text = query.text
        if self.config.char_normalize:
            text = self.normalize(text)
        if self.config.lowercase:
            text = self.lowercase_text(text)
        tokens = self.tokenize(text)
        if self.config.stem:
            tokens = self.stem(tokens)
        text = ' '.join(tokens)
        return Query(query.id, query.lang, text)
