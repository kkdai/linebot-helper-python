# Adjust the import as necessary
import os
import logging
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Set the user agent
os.environ["USER_AGENT"] = "myagent"


def docs_to_str(docs: list[Document]) -> str:
    return "\n".join([doc.page_content for doc in docs])


def generate_twitter_post(input_text: str) -> str:
    '''
    Generate a Twitter post using the Google Generative AI model.
    '''
    model = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.5,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """
Rewrite the entire article to make it suitable for a Twitter post that is eye-catching, includes hashtags, and uses Taiwanese expressions for a local touch.
"{text}"

# Steps

1. **Summarize Key Points**: Extract the main idea or message of the article. Condense it into one or two short, engaging sentences that fit Twitter's character limit (280 characters).
2. **Use Taiwanese Expressions**: Adapt the language of the tweet to incorporate local Taiwanese phrases or vocabulary to appeal to the Taiwanese audience.
3. **Add Hashtags**: Include 2-5 relevant hashtags to broaden reach and catch the attention of potential readers. The hashtags should be related to the article's subject matter and written in a Taiwanese conversational style.
4. **Include a Hook**: Write a compelling opening to immediately grab attention. This might be a question, a surprising fact, or a striking opinion drawn from the article.
5. **CTA (Call to Action)**: Add a prompt encouraging interaction or clicking on the link, such as "點我看更多喔" (Click here for more) or "你怎麼看呢？" (What do you think?).
6. **Link to Article** (Optional): Include a shortened link to the original article where needed.

# Output Format

- One or two concise tweets.
- Each tweet must be 280 characters or less.
- Incorporate local Taiwanese phrases where appropriate.
- Include 2-5 relevant hashtags.
- Include a call to action to encourage engagement.

# Examples

**Input**:
An article discussing the impact of digital detox on productivity.

**Output**:
"最近覺得科技讓你抓狂嗎？試著來個數位排毒吧📵，也許能幫你找回專注力跟生活的平衡 #數位排毒 #集中注意力 #生活態度 點我看更多喔: [link]"

**Input**:
An article exploring the benefits of adopting renewable energy.

**Output**:
"台灣的未來就是要綠能！用太陽能不但環保還可以省荷包💰。大家一起投入綠色行動吧！#再生能源 #減碳 #綠能生活 🌱 記得來看看喔: [link]"

# Notes

- Make sure each tweet is engaging and uses expressions familiar to a Taiwanese audience.
- Hashtags should be popular and relevant, and written in a way that resonates locally.
- Tweets should be easy for readers to grasp and encourage sharing.
"""
    prompt = PromptTemplate.from_template(prompt_template)

    chain = prompt | model
    tweet = chain.invoke(
        {"text": input_text})
    return tweet.content


def generate_slack_post(input_text: str) -> str:
    '''
    Generate a Slack post using the Google Generative AI model.
    '''
    model = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.5,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """
    Provide a slack post base on provided text.
    多一點條例式，然後多一些 slack emoji:
    "{text}"
    Remove all markdown.
    Reply in ZH-TW"""
    prompt = PromptTemplate.from_template(prompt_template)

    chain = prompt | model
    tweet = chain.invoke(
        {"text": input_text})
    return tweet.content


def summarize_text(text: str, max_tokens: int = 100) -> str:
    '''
    Summarize a text using the Google Generative AI model.
    '''
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """用台灣用語的繁體中文，簡潔地以條列式總結文章重點。在摘要後直接加入相關的英文 hashtag，以空格分隔。內容來源可以是網頁、文章、論文、影片字幕或逐字稿。

    原文： "{text}"
    請遵循以下步驟來完成此任務：

    # 步驟
    1. 從提供的內容中提取重要重點，無論來源是網頁、文章、論文、影片字幕或逐字稿。
    2. 將重點整理成條列式，確保每一點為簡短且明確的句子。
    3. 使用符合台灣用語的簡潔繁體中文。
    4. 在摘要結尾處，加入至少三個相關的英文 hashtag，並以空格分隔。

    # 輸出格式
    - 重點應以條列式列出，每一點應為一個短句或片語，語言必須簡潔明瞭。
    - 最後加入至少三個相關的英文 hashtag，每個 hashtag 之間用空格分隔。

    # 範例
    輸入：
    文章內容：
    台灣的報告指出，環境保護的重要性日益增加。許多人開始選擇使用可重複使用的產品。政府也實施了多項政策來降低廢物。

    摘要：

    輸出：
    - 環境保護重要性增加
    - 越來越多人使用可重複產品
    - 政府實施減廢政策
    #EnvironmentalProtection #Sustainability #Taiwan
    """

    prompt = PromptTemplate.from_template(prompt_template)

    summarize_chain = load_summarize_chain(
        llm=llm, chain_type="stuff", prompt=prompt)
    document = Document(page_content=text)
    summary = summarize_chain.invoke([document])
    return summary["output_text"]
