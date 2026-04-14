import re
from token import tok_name

import nltk
from nltk import ngrams
from nltk.corpus import stopwords
from nltk.tokenize import wordpunct_tokenize  # best for Arabic
from nltk.tokenize import word_tokenize  # best for latin-based

import string
from Levenshtein import distance
import functools
from statistics import mean
from pathlib import Path

from sentence_transformers import SentenceTransformer, util  # original tested sentence_transformers version 2.3.1

import spacy
from spacy.lang.char_classes import ALPHA, ALPHA_LOWER, ALPHA_UPPER
from spacy.lang.char_classes import CONCAT_QUOTES, LIST_ELLIPSES, LIST_ICONS
from spacy.util import compile_infix_regex
from spacy.matcher import Matcher
from spacy.cli import download

from term_extractor.model_lang_maps import SPACY_LANG_SUPPORT, NLTK_LANG_SUPPORT

custom_en_infixes = (
        LIST_ELLIPSES
        + LIST_ICONS
        + [
            r"(?<=[0-9])[+\\-\\*^](?=[0-9-])",
            r"(?<=[{al}{q}])\\.(?=[{au}{q}])".format(
                al=ALPHA_LOWER, au=ALPHA_UPPER, q=CONCAT_QUOTES
            ),
            r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
            # ✅ Commented out regex that splits on hyphens between letters:
            # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS),
            r"(?<=[{a}0-9])[:<>=/](?=[{a}])".format(a=ALPHA),
        ]
)


class NLPTasks:
    def __init__(self, language: str, method="ngrams"):
        self._lang = language
        self._method = method
        self._setup_lang()

    @staticmethod
    def _ensure_nltk_resources(resources):
        search_dirs = [
            "corpora", "tokenizers", "taggers", "chunkers",
            "help", "models", "misc", "stemmers", "classifiers"
        ]

        downloaded = []

        for resource in resources:
            found = False
            for d in search_dirs:
                try:
                    nltk.data.find(f"{d}/{resource}")
                    found = True
                    break
                except LookupError:
                    continue
            if not found:
                nltk.download(resource, quiet=True)
                downloaded.append(resource)

        if downloaded:
            print(f"Downloaded: {', '.join(downloaded)}")
        else:
            print("All requested NLTK resources are already available.")

    def _setup_lang(self):
        # quiet = False
        # nltk.download('stopwords', quiet=quiet)
        # nltk.download('punkt', quiet=quiet)
        # nltk.download("punkt_tab", quiet=quiet)
        NLPTasks._ensure_nltk_resources(["stopwords", "punkt", "punkt_tab"])


        if self._method == "spacy":
            self._load_spacy_model()

        self.stop_words = set(stopwords.words(NLTK_LANG_SUPPORT[self._lang]))
        self._quote_marks = r"\"'“”’‘‛〞〝«»‹›"  # todo: improve handling of quotes
        self.puncts = string.punctuation + self._quote_marks
        if self._lang == "en":
            self.stop_words.update(['therefore', 'every', 'each', 'also', 'might', '\'s', 'ii', 'iii', 'xxi', 'iv', 'vi', 'within'])
            infix_re = compile_infix_regex(custom_en_infixes)
            if self._method == "spacy":
                self.spacy_nlp.tokenizer.infix_finditer = infix_re.finditer
        if self._lang == "ar":
            self.stop_words.update(['لماذا', 'ربما'])
            self.puncts = self.puncts + "ـ،؛؟"
        print(f"NLP setup complete for '{self._lang}'")

    def _load_spacy_model(self):
        # download spacy's model if necessary, then load it
        if self._lang in SPACY_LANG_SUPPORT:
            model_name = SPACY_LANG_SUPPORT[self._lang]
            try:
                print(f"Loading spacy's {model_name}")
                self.spacy_nlp = spacy.load(model_name)
            except OSError:
                print(f"Downloading spacy's {model_name}")
                download(model_name)
                self.spacy_nlp = spacy.load(model_name)

    def _deprecated_spacy_extract_terms(self, text: str):
        if self._lang != "en":
            return  # only supports English for now
        pats = []
        # over-the-counter medications
        pats.append([{'POS': 'ADV', 'TEXT': {'REGEX': r'-'}, 'OP': '*'}, {'POS': {'IN': ['ADJ', 'NOUN']}, 'IS_STOP': False, 'OP': '*'}])
        pats.append([{'POS': 'NOUN', 'OP': '*'}, {'POS': 'ADJ', 'IS_STOP': False, 'OP': '*'}, {'POS': 'NOUN', 'OP': '+'}])
        # Centers for Disease and Control | Food and Drug Administration | World Health Organization
        pats.append([{'POS': 'PROPN', 'OP': '+'}, {'POS': {'IN': ['CCONJ', 'ADP', 'PROPN']}, 'OP': '*'}, {'POS': 'PROPN', 'OP': '+'}])
        # Apple | Microsoft
        pats.append([{'POS': 'PROPN', 'OP': '+'}])  # ADP
        # Apple stocks | Microsoft shares
        pats.append([{'POS': 'PROPN', 'OP': '*'}, {'POS': 'NOUN', 'OP': '+'}])
        # Phrasal verbs
        pats.append([{'POS': 'VERB', 'OP': '{1}'}, {'POS': 'ADV', 'OP': '*'}, {'POS': 'ADP', 'OP': '{1,2}'}])
        pats.append([{'POS': 'VERB', 'OP': '{1}'}, {'POS': 'ADP', 'OP': '{0,2}'}])
        # pats = [[{'POS': 'VERB', 'OP': '{1}'}, {'POS': 'ADV', 'OP': '*'}, {'POS': 'ADP', 'OP': '{1,2}'}]]
        doc = self.spacy_nlp(text)
        for token in doc:
            break
            #print(token.text, token.pos_, token.tag_, token.dep_)
        matcher = Matcher(self.spacy_nlp.vocab)
        matcher.add("terms", pats, greedy='LONGEST')
        matches = matcher(doc, as_spans=True)
        ents = []
        for span in matches:
            if span.text not in ents:
                ents.append(span.text)
        # ents = set([span.text for span in matches if span.text])
        return ents

    def _clean_spacy_chunks(self, text: str):
        super_exclude = [r"^\d+%*$", r"https*://"]  # exclusion rules for all languages, which can be extended below per language
        # trim articles and prepositions that surround noun phrases
        if self._lang == "en":
            # noun phrase parts that are not essential for terminology
            remove = "|".join(
                "\\d+ no a an the in this these our his her your you yours from any every their further its all other some  more less one two three four five six seven eight nine ten".split())
            exclude = super_exclude  # patterns to exclude
            text = re.sub(rf"^({remove}) ", "", text, flags=re.IGNORECASE)

            if text.lower() in self.stop_words or any([re.match(item, text.lower()) for item in exclude]):
                text = ""
        return text

    def spacy_extract_terms(self, text: str):
        if self._lang not in SPACY_LANG_SUPPORT.keys():
            raise ValueError(f"Language {self._lang} not supported yet.")
        ents = set()
        doc = self.spacy_nlp(text)
        for chunk in doc.noun_chunks:
            clean = self._clean_spacy_chunks(chunk.text)
            if clean != "":
                ents.add(clean)
        return ents

    def tok_ngrams(self, text: str, n1: int, n2: int = None, skip_peri_stop_words: bool = False):
        toks = self._tokenize_keep_mid_puncts(text)
        ngs = self._ngarm_by_range(toks, n1, n2, skip_peri_stop_words)
        return ngs

    def _ngarm_by_range(self, tokens: list, n1: int, n2: int = None, skip_peri_stop_words: bool = False):
        if n2 is None:
            n2 = n1
        ngrams_set = set()
        for n in range(n1, n2 + 1):
            ngs = ngrams(tokens, n)
            # skip ngrams with peripheral stop words
            if skip_peri_stop_words:
                ngs = [ng for ng in ngs if not any([ng[0].lower() in self.stop_words, ng[-1].lower() in self.stop_words])]
            # excludes ngrams that consist entirely of stop words
            ngs = [ng for ng in ngs if not all([tok.lower() in self.stop_words for tok in ng])]
            # ngs = [ng for ng in ngrams(tokens, n) if not all([tok.lower() in self.stop_words for tok in ng])]  # excludes ngrams that consist entirely of stop words
            result = [" ".join(ngram) for ngram in ngs]
            if len(result) > 0:
                # Exclude fragments that end or start with punctuation
                for fragment in result:
                    if re.search(rf"(^[{self.puncts}]|[{self.puncts}]$)", fragment.strip()) is None:
                        if re.fullmatch(r"[0-9\s\-\\/.,\u0660-\u0669]+", fragment):  # skip phrases consisting solly of numbers
                            continue
                        ngrams_set.add(re.sub(rf" ([{self.puncts}])", r"\1", fragment))
        return ngrams_set

    def _tokenize_keep_mid_puncts(self, sent: str):
        """
        Removes punctuation inside the sentence
        """
        if self._lang == "ar":
            sent = re.sub("[\u064B-\u0652\u0640]", "", sent)  # remove arabic diacritics
        # remove end puncts
        sent = re.sub(f"[{self.puncts}]$", "", sent)
        sent = re.sub(r"[()]", "", sent)
        # apostrophe workaround
        sent = re.sub("['’‘´]", '|_apo_|', sent)
        # tokenizer = WhitespaceTokenizer()
        # word_tokens = tokenizer.tokenize(sent)
        if self._lang == "ar":
            word_tokens = wordpunct_tokenize(sent)
        else:
            word_tokens = word_tokenize(sent, NLTK_LANG_SUPPORT[self._lang])
        word_tokens = [tok.replace('|_apo_|', "'") for tok in word_tokens]
        # print(word_tokens)
        return word_tokens

    @staticmethod
    @functools.lru_cache
    def _normalize_arabic_letters(text: str):
        text = re.sub("[أآإ]", "ا", text)
        text = re.sub("[ؤ]", "و", text)
        text = re.sub("[ئ]", "ى", text)
        return text

    # lev based similarity
    @staticmethod
    @functools.lru_cache
    def lev_sim(str1: str, str2: str, penalize_shortness=False):
        # penalization factor for short strings
        pen_factor = 1
        if len(str1) <= 7 >= len(str2) and penalize_shortness:
            pen_factor = 0.8
        max_len = max(len(str1), len(str2))
        return (1 - distance(str1, str2) / max_len) * pen_factor

    @staticmethod
    @functools.lru_cache
    def lev_sim_tok_based(str1: str, str2: str, tok_min_lev_sim: float = 0.6, force_equal_tok_count=False, penalize_shortness=False, lang=""):
        # finds levenshtein similarity between parallel tokens in two strings
        # if any parallel tokens fail to meet tok_min_lev_sim threshold, the entire match fails (i.e., returns 0)
        if lang == "ar":
            str1 = NLPTasks._normalize_arabic_letters(str1)
            str2 = NLPTasks._normalize_arabic_letters(str2)
        str1_toks = str1.split()
        str2_toks = str2.split()
        if force_equal_tok_count and len(str1_toks) != len(str2_toks):
            return 0
        if len(str1_toks) > len(str2_toks):  # str_1 should have more tokens for partial search
            return 0
        ngram_len = len(str1_toks)
        str2_ngrams = ngrams(str2_toks, ngram_len)

        top_lev_score_avg = 0  # collect highest achieved lev sim
        for str2_ngram in str2_ngrams:
            tok_for_tok_sim = [NLPTasks.lev_sim(str1_toks[i], str2_ngram[i], penalize_shortness) for i in range(ngram_len)]
            # nullify low sims
            tok_for_tok_sim = [sim if sim >= tok_min_lev_sim else 0 for sim in tok_for_tok_sim]
            # print(tok_for_tok_sim)
            lev_sim_avg = 0 if 0 in tok_for_tok_sim else mean(tok_for_tok_sim)
            top_lev_score_avg = lev_sim_avg if lev_sim_avg > top_lev_score_avg else top_lev_score_avg

        return top_lev_score_avg * (len(str1_toks) / len(str2_toks))


class LLMCompare:
    def __init__(self, model: str = 'LaBSE'):
        if model not in {'intfloat/multilingual-e5-base', 'LaBSE'}:
            raise ValueError(f"Model '{model}' is not supported.")
        self.module_name = model
        self.model = SentenceTransformer(self.module_name)  #original tested version 2.3.1

    def embed_text(self, text: str):
        return self.model.encode([text])

    def sen_sim(self, emb1, emb2):
        sim = float(util.cos_sim(emb1, emb2)[0])
        #sim = 0 if sim <= 0.5 else (sim - 0.5) * 2
        return sim


if __name__ == '__main__':

    # a = "15/ 555/888 555-999 555-5"
    a = "Call this number: 555-666-999 ((toll-free)"
    a = "Call this number: 555-666-999 &quot;toll-free&quot;"
    a = "أرحب بــــالقرار 15/25 والقَــُــُـــــــرار 15/ الذي  ــ ـ"
    a = "The acceptance of a court's jurisdiction by a State would be done by separate act. November and December are great."

    b = NLPTasks('en')
    c = b.tok_ngrams(a, 1, 4, True)

    for d in c:
        print(d)
