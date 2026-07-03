import google.generativeai as genai

genai.configure(api_key="GEMINI_API_KEY")

model = genai.GenerativeModel("gemini-flash-latest")

response = model.generate_content("Say hello in one word")

print(response.text)