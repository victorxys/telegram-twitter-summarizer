
import os
import google.generativeai as genai
from dotenv import load_dotenv

# 从 .env 文件加载环境变量
load_dotenv()

def test_gemini_key():
    """
    专门用于测试 .env 文件中的 GEMINI_API_KEY 是否有效。
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ 错误: 在 .env 文件中未找到 GEMINI_API_KEY。")
        return

    # 【新的调试步骤】打印出加载到的 Key 的一部分，用于核对
    print("-" * 50)
    print(f"脚本加载到的 API Key (前5位和后5位): {api_key[:5]}...{api_key[-5:]}")
    print("请仔细核对，这是否与你 curl 命令中使用的、能成功的那个 Key 完全一致。")
    print("-" * 50)

    print("\n正在尝试使用此 API 密钥连接到 Gemini...")

    try:
        genai.configure(api_key=api_key)
        
        # 我们使用你确认过的模型名称
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        print("API 密钥配置成功。正在生成测试响应...")
        
        response = model.generate_content("This is a test. If you see this, respond with the word 'OK'.")
        
        print("\n--- Gemini 测试结果 ---")
        if 'OK' in response.text:
            print("✅ 成功: API 密钥有效且工作正常。")
        else:
            print(f"⚠️ 意外的响应: 密钥可能是有效的，但模型返回了: {response.text}")

    except Exception as e:
        print("\n--- Gemini 测试结果 ---")
        print(f"❌ 失败: API 密钥无效，或存在连接问题。")
        print(f"错误详情: {e}")

if __name__ == "__main__":
    test_gemini_key()
