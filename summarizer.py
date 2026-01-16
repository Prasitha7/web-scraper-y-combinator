from transformers import pipeline

class TextSummarizer:
    def __init__(
        self,
        model_name="facebook/bart-large-cnn",
        device=-1,  # -1 = CPU, 0 = GPU
        max_chunk_tokens=900
    ):
        """
        BART-large-cnn works best below ~1024 tokens.
        """
        self.summarizer = pipeline(
            "summarization",
            model=model_name,
            device=device
        )
        self.max_chunk_tokens = max_chunk_tokens

    def _chunk_text(self, text: str):
        words = text.split()
        chunks = []
        current = []

        for word in words:
            current.append(word)
            if len(current) >= self.max_chunk_tokens:
                chunks.append(" ".join(current))
                current = []

        if current:
            chunks.append(" ".join(current))

        return chunks

    def summarize(self, text: str, max_new_tokens=120, min_length=40) -> str:
        """
        Silent, safe summarization (no terminal spam)
        """
        if not text or len(text.strip()) < 50:
            return text

        chunks = self._chunk_text(text)
        summaries = []

        for chunk in chunks:
            result = self.summarizer(
                chunk,
                max_new_tokens=max_new_tokens,
                min_length=min_length,
                do_sample=False
            )
            summaries.append(result[0]["summary_text"])

        # Hierarchical summarization if needed
        if len(summaries) > 1:
            combined = " ".join(summaries)
            final = self.summarizer(
                combined,
                max_new_tokens=max_new_tokens,
                min_length=min_length,
                do_sample=False
            )
            return final[0]["summary_text"]

        return summaries[0]
