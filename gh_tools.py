import os
from datetime import datetime, timedelta, timezone

from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains.summarize import load_summarize_chain
from langchain_community.document_loaders import GitHubIssuesLoader

prompt_template = """
這些資料是我昨天搜集的文章，我想要總結這些資料，請幫我總結一下。 寫成一篇短文來分享我昨天有學到哪些內容，
幫我在每一段最後加上原有的 URL 連結，這樣我可以隨時回去查看原文。 
請去除掉所有的 tags, links, 和其他不必要的資訊，只保留文章的主要內容，我的角色是 Evan ，喜歡 LLM 跟 AI 相關的技術。:
"{text}"
CONCISE SUMMARY:
Reply in ZH-TW"""
prompt = PromptTemplate.from_template(prompt_template)


def summarized_yesterday_github_issues() -> str:
    total_github_issues = 0
    past_days = 1

    # 擷取至少五個
    while total_github_issues <= 5:
        since_day = (datetime.now(timezone.utc) - timedelta(days=past_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        GH_ACCESS_TOKEN = os.getenv("GITHUB_TOKEN")
        loader = GitHubIssuesLoader(
            repo="kkdai/bookmarks",
            # delete/comment out this argument if you've set the access token as an env var.
            access_token=GH_ACCESS_TOKEN,
            include_prs=False,
            since=since_day,
        )
        docs = loader.load()
        print(f"總共有: {len(docs)} 筆資料")
        total_github_issues = len(docs)
        past_days += 1

    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )
    chain = load_summarize_chain(llm, chain_type="stuff", prompt=prompt)
    summary = chain.invoke(docs)
    return summary["output_text"]
