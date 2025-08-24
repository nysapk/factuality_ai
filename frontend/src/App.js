import React, { useState } from "react";
import "./App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Header = () => (
  <header className="bg-gradient-to-r from-blue-600 to-purple-700 text-white py-6 px-4 shadow-lg">
    <div className="container mx-auto">
      <h1 className="text-3xl font-bold mb-2">🎯 Factuality</h1>
      <p className="text-blue-100">Real-time Fact Checker for YouTube Videos</p>
    </div>
  </header>
);

function App() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!youtubeUrl.trim()) {
      setError("Please enter a YouTube URL");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await axios.post(`${API}/fact-check/youtube`, {
        url: youtubeUrl.trim(),
      });
      setResult(response.data);
    } catch (error) {
      setError(
        error.response?.data?.detail ||
          "An error occurred while processing the video"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />

      <div className="container mx-auto px-4 py-8">
        <div className="bg-white rounded-lg shadow-md p-6 mb-8">
          <h2 className="text-xl font-semibold mb-4">Analyze YouTube Video</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                YouTube URL
              </label>
              <input
                type="url"
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={loading}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 text-white py-3 px-6 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {loading ? "Analyzing..." : "🔍 Analyze Video"}
            </button>
          </form>

          {error && (
            <div className="mt-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded-lg">
              {error}
            </div>
          )}
        </div>

        {result && <pre className="bg-gray-100 p-4 rounded">{JSON.stringify(result, null, 2)}</pre>}
      </div>
    </div>
  );
}

export default App;
