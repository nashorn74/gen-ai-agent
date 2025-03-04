import { useState, useEffect } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from '/vite.svg'
import './App.css'

function App() {
  const [message, setMessage] = useState("");   // 백엔드에서 가져온 "Hello from FastAPI!"
  const [question, setQuestion] = useState(""); // 사용자 입력 질문
  const [answer, setAnswer] = useState("");     // OpenAI 응답

  // 기존 FastAPI 루트("/") 응답
  useEffect(() => {
    fetch("http://localhost:8000")
      .then((res) => res.json())
      .then((data) => {
        setMessage(data.message);
      })
      .catch((err) => console.error(err));
  }, []);

  // 질문 전송 함수
  const handleAsk = async () => {
    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: question }),
      });
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
      const data = await res.json();
      setAnswer(data.answer); // { answer: "...GPT 응답..." }
    } catch (error) {
      console.error(error);
      setAnswer("오류가 발생했습니다.");
    }
  };

  return (
    <>
      <div>
        <a href="https://vite.dev" target="_blank">
          <img src={viteLogo} className="logo" alt="Vite logo" />
        </a>
        <a href="https://react.dev" target="_blank">
          <img src={reactLogo} className="logo react" alt="React logo" />
        </a>
      </div>
      <h1>Vite + React + FastAPI</h1>

      <p>Message from server: {message}</p>

      <div style={{ marginTop: "2rem" }}>
        <h2>Chat with OpenAI:</h2>
        <div>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="질문을 입력하세요"
            style={{ width: "300px" }}
          />
          <button onClick={handleAsk} style={{ marginLeft: "8px" }}>
            Ask
          </button>
        </div>
        {answer && (
          <div style={{ marginTop: "1rem", whiteSpace: "pre-line" }}>
            <strong>Answer:</strong> {answer}
          </div>
        )}
      </div>
    </>
  );
}

export default App;
