import csv
import dataclasses
import json
import pathlib

from .config import BaseConfig, Optional
from .error import ConfigError, ParseError
from .pipeline import Task
from .schema import TopicsInputConfig
from .text import Splitter, TextProcessor
from .util import trec, DataclassJSONEncoder, InputIterator, ReaderFactory
from .util.file import count_lines, count_lines_with, path_append


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


class TopicReaderFactory(ReaderFactory):
    classes = {
        'sgml': 'SgmlTopicReader',
        'xml': 'XmlTopicReader',
        'json': 'Tc4JsonTopicReader',
        'jsonl': 'Tc4JsonTopicReader',
        'msmarco': 'TsvTopicReader'
    }
    config_class = TopicsInputConfig
    name = 'topic type'


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


class SgmlTopicReader(InputIterator):
    """Iterator over topics from trec sgml"""

    def __init__(self, path, encoding, lang, prefix, strip_non_digits):
        self.path = path
        self.encoding = encoding
        self.lang = lang
        self.strip_non_digits = strip_non_digits
        self.topics = iter(topic for topic in trec.parse_sgml_topics(path, encoding, prefix))

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        identifier = ''.join(filter(str.isdigit, topic[0])) if self.strip_non_digits else topic[0]
        return Topic(identifier, self.lang, topic[1], topic[2], topic[3])

    def __len__(self):
        return count_lines_with('<top>', self.path, self.encoding)


class XmlTopicReader(InputIterator):
    """Iterator over topics from trec xml"""

    def __init__(self, path, encoding, lang, strip_non_digits, **kwargs):
        self.path = path
        self.encoding = encoding
        self.lang = lang
        self.strip_non_digits = strip_non_digits
        self.topics = iter(topic for topic in trec.parse_xml_topics(path, encoding))

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        identifier = ''.join(filter(str.isdigit, topic[0])) if self.strip_non_digits else topic[0]
        return Topic(identifier, topic[1], topic[2], topic[3], topic[4])

    def __len__(self):
        return count_lines_with('<topic', self.path, self.encoding)


class Tc4JsonTopicReader(InputIterator):
    """Iterator over topics from jsonl file """

    def __init__(self, path, encoding, lang, **kwargs):
        """
        Args:
            path (str): Path to topics file.
            encoding (str): File encoding.
            lang (str): Language of the topics.
            **kwargs (dict): Unused
        """
        self.path = path
        self.encoding = encoding
        self.lang = lang
        self.topics = iter(self.parse(path, encoding))

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.topics)

    def __len__(self):
        return count_lines(self.path, self.encoding)

    def construct(self, data):
        try:
            title = data['topic_name'].strip()
            desc = data['topic_description'].strip()
            return Topic(data['topic_id'], self.lang, title, desc, None)
        except KeyError as e:
            raise ParseError(f"Missing field {e} in json docs element: {data}")

    def parse(self, path, encoding='utf8'):
        with open(path, 'r', encoding=encoding) as fp:
            try:
                return [self.construct(json.loads(data)) for data in fp]
            except json.decoder.JSONDecodeError as e:
                raise ParseError(f"Problem parsing json from {path}: {e}")


class TsvTopicReader(InputIterator):
    """Iterator over topics from tsv file like MSMARCO"""

    def __init__(self, path, encoding, lang, **kwargs):
        self.path = path
        self.encoding = encoding
        self.lang = lang
        self.topics = iter(topic for topic in self.parse(path, encoding))

    def __iter__(self):
        return self

    def __next__(self):
        topic = next(self.topics)
        return Topic(topic[0], self.lang, topic[1], None, None)

    def __len__(self):
        return count_lines(self.path, self.encoding)

    @staticmethod
    def parse(path, encoding='utf8'):
        with open(path, 'r', encoding=encoding) as fp:
            reader = csv.reader(fp, delimiter='\t')
            for line in reader:
                yield line[0], line[1].strip()


class QueryWriter(Task):
    """Write queries to a jsonl file using internal format"""

    def __init__(self, config, artifact_config):
        """
        Args:
            config (OutputConfig): Config that includes output.path.
            artifact_config (BaseConfig or None): Config that resulted in this artifact
        """
        super().__init__(artifact_config, config.output.path)
        path = self.base / 'queries.jsonl'
        self.file = open(path, 'w')

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
        super().end()
        self.file.close()

    def reduce(self, dirs):
        for base in dirs:
            path = path_append(base, 'queries.jsonl')
            with open(path) as fp:
                for line in fp:
                    self.file.write(line)


class QueryReader(InputIterator):
    """Iterator over queries from jsonl file """

    def __init__(self, path):
        self.path = pathlib.Path(path)
        if self.path.is_dir():
            self.path = self.path / 'queries.jsonl'
        with open(self.path) as fp:
            self.data = fp.readlines()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return Query(**json.loads(self.data.pop(0)))
        except IndexError:
            raise StopIteration()

    def __len__(self):
        return count_lines(self.path)

    def peek(self):
        return Query(**json.loads(self.data[0]))


class QueryProcessor(Task, TextProcessor):
    """Query Preprocessing"""

    def __init__(self, config, lang):
        """
        Args:
            config (TextProcessorConfig)
            lang (str)
        """
        Task.__init__(self)
        TextProcessor.__init__(self, config, lang)
        self.splitter = Splitter(config.splits)

    def process(self, query):
        """
        Args:
            query (Query)

        Returns
            Query
        """
        self.splitter.reset()
        text = query.text
        if self.config.normalize:
            text = self.normalize(text)
        tokens = self.tokenize(text)
        self.splitter.add('tokenize', Query(query.id, query.lang, ' '.join(tokens)))
        if self.config.lowercase:
            tokens = self.lowercase(tokens)
        self.splitter.add('lowercase', Query(query.id, query.lang, ' '.join(tokens)))
        if self.config.stopwords:
            tokens = self.remove_stop_words(tokens, not self.config.lowercase)
        self.splitter.add('stopwords', Query(query.id, query.lang, ' '.join(tokens)))
        if self.config.stem:
            tokens = self.stem(tokens)
        self.splitter.add('stem', Query(query.id, query.lang, ' '.join(tokens)))

        if self.splitter:
            return self.splitter.get()
        else:
            return Query(query.id, query.lang, ' '.join(tokens))

    @property
    def name(self):
        if self.splitter:
            return f"{super()} | Splitter"
        else:
            return str(super())