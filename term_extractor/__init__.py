"""
TMX converter package.
"""

__version__ = "1.3.0"

# Import main public API
from .magic import Extractor, lev_sim
from .model_lang_maps import LABSE_LANG_SUPPORT, NLTK_LANG_SUPPORT, SPACY_LANG_SUPPORT
from .nlp_lib import NLPTasks, LLMCompare, custom_en_infixes

__all__ = ['Extractor',
           'lev_sim',
           'LABSE_LANG_SUPPORT',
           'NLTK_LANG_SUPPORT', 'SPACY_LANG_SUPPORT',
           'NLPTasks',
           'LLMCompare',
           'custom_en_infixes']
