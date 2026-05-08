from google import genai

client = genai.Client(api_key="AIzaSyCVt_7-Y-yqfe-BxfCpURKnA9t5Fsa8VW0")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello"
)

print(response.text)