import time

from term_extractor.magic import Extractor


def consume(gen):
    """Consume a generator, printing status messages and returning the last result."""
    result = None
    for msg in gen:
        msg_type = msg.get("type")
        if msg_type == "status":
            print(msg["message"])
        elif msg_type == "progress":
            print(f"{msg['label']}: {msg['pct']}%")
        elif msg_type == "step":
            print(f"Step {msg['step'] + 1}: {msg['name']}")
        elif msg_type == "result":
            result = msg.get("data")
    return result


if __name__ == "__main__":
    start_time = time.time()
    TE = Extractor()

    # TE.load_pred_src_terms(r"C:\Users\blazi\Dropbox\Python Stuff\Term-Extractor-Test-Data\pred_mesh_terms.txt")
    # TE.load_pred_src_terms(r"C:\Users\blazi\Dropbox\Python Stuff\Term-Extractor-Test-Data\new_pred_legal_terms.txt")
    # TE.load_pred_src_terms(r"data\pred_legal_terms.txt")
    # TE.load_pred_src_terms(r"data\pred_temp.txt")

    TE.min_source_rep = 50
    TE.max_source_rep = 100
    TE.min_llm_score = 0.4
    TE.target_dismiss = 15
    TE.min_count_ratio = 0.5
    TE.grouping_min_lev_sim = 0.65
    TE.max_sentence_length = 300
    TE.max_translation_pairs = 10_000
    TE.max_1st_cleanup_cand_count = 50
    TE.max_grouping_cand_count = 50
    TE.skip_top_common_words = 10_000
    TE.skip_peri_stop_words = True
    TE.model = 'intfloat/multilingual-e5-base'  # intfloat/multilingual-e5-base  OR  LaBSE
    TE.enable_partial_points = False
    TE.llm_scoring = False
    TE.verbose_logging = False
    TE.src_term_extraction_method = "spacy"  # ngrams = default | spacy
    data_set = r"C:\Users\blazi\Desktop\Veeva Demo files\WHO-en-ar.csv"
    # data_set = r"C:\Users\blazi\Downloads\covid-tms-public\en_fr.csv"
    # data_set = r"C:\Users\blazi\Downloads\un-paral-ar-en.tmx\un-par-en-ar.csv"
    # data_set = r"C:\Users\blazi\Dropbox\Python Stuff\Term-Extractor-Test-Data\tmx-exp-mc-deduped.csv"
    # data_set = r"C:\Users\blazi\Dropbox\Python Stuff\Term-Extractor-Test-Data\un-docs-en-ar.csv"
    # data_set = r"C:\Users\blazi\Downloads\temp_conv\automl-csv\en_ar_23-10-2025-10-25-13-AM.csv"
    # data_set = r"C:\Users\blazi\Dropbox\Python Stuff\Term-Extractor-Test-Data\un-docs-en-ar.csv"  # Laptop
    # data_set = r"C:\Users\blazi\Downloads\temp_conv\un\un-tm-ar-en-13.4m.csv"
    # data_set = r"C:\Users\blazi\Downloads\temp_conv\un\un-tm-en-ar-13.4m.csv"
    data_path = ""

    t = time.time()
    consume(TE.load_translations(f"{data_path}{data_set}", "en", "ar"))
    elapsed_time = (time.time() - t) / 60
    print(f"Loading time: {elapsed_time} mins")

    tar_path = r"C:\Users\blazi\Downloads\temp_conv\term_ext"
    consume(TE.match_terms(rf"{tar_path}\extracted_terms.xlsx", True, True))
    duration = time.time() - start_time
    print(f"Duration: {duration / 60} minutes")
    # TODO: PEND - fix HTML decoding, like can&#x27;t (Spanish sample)
    # TODO: PEND - exclude source-equal-target (see Spanish sample)It
    # TODO: make partial gains optional
