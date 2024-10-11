from langchain_core.documents import Document


def docs_to_str(docs: list[Document]) -> str:
    return "\n".join([doc.page_content.strip() for doc in docs])
