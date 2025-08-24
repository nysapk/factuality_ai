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

const StatsSummary = ({ result }) => {
  const total = result.total_claims;
  const getPercentage = (count) => (total > 0 ? Math.round((count / total) * 100) : 0);

  return (
    <div className="bg-white rounded-lg shadow-md p-6 mb-6">
      <h3 className="text-lg font-semibold mb-4">Analysis Summary</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="text-center">
          <div className="text-2xl font-bold text-green-600">{result.true_claims}</div>
          <div className="text-sm text-gray-600">True ({getPercentage(result.true_claims)}%)</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-red-600">{result.false_claims}</div>
          <div className="text-sm text-gray-600">False ({getPercentage(result.false_claims)}%)</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-orange-600">{result.partial_claims}</div>
          <div className="text-sm text-gray-600">Partial ({getPercentage(result.partial_claims)}%)</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-gray-600">{result.unverified_claims}</div>
          <div className="text-sm text-gray-600">Unverified ({getPercentage(result.unverified_claims)}%)</div>
        </div>
      </div>
      <div className="text-sm text-gray-600">
        <div>📺 <strong>Video:</strong> {result.video_title}</div>
        <div>📺 <strong>Channel:</strong> {result.channel_name}</div>
        <div>⏱️ <strong>Processing Time:</strong> {result.processing_time.toFixed(2)}s</div>
        <div>📝 <strong>Transcript Length:</strong> {result.transcript_length} segments</div>
      </div>
    </div>
  );
};

const ClaimCard = ({ claim }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case "true":
        return "bg-green-100 border-green-400 text-green-800";
      case "false":
        return "bg-red-100 border-red-400 text-red-800";
      case "partial":
        return "bg-orange-100 border-orange-400 text-orange-800";
      default:
        return "bg-gray-100 border-gray-400 text-gray-800";
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case "true":
        return "✅";
      case "false":
        return "❌";
      case "partial":
        return "⚠️";
      default:
        return "❓";
    }
  };

  return (
    <div className={`border-l-4 p-4 mb-4 rounded-r-lg ${getStatusColor(claim.factual_status)}`}>
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-medium bg-white px-2 py-1 rounded">{claim.timestamp}</span>
        <div className="flex items-center space-x-2">
          <span className="text-lg">{getStatusIcon(claim.factual_status)}</span>
          <span className="text-sm font-semibold capitalize">{claim.factual_status}</span>
          <span className="text-xs bg-white px-2 py-1 rounded">
            {Math.round(claim.confidence_score * 100)}%
          </span>
        </div>
      </div>
      <blockquote className="font-medium mb-3 text-gray-900">"{claim.text}"</blockquote>
      <div className="text-sm text-gray-700 mb-2">
        <strong>Context:</strong> {claim.context}
      </div>
      <div className="text-sm text-gray-700 mb-3">
        <strong>Analysis:</strong> {claim.explanation}
      </div>
      {claim.sources?.length > 0 && (
        <div className="text-xs">
          <strong>Sources:</strong>
          <ul className="list-disc list-inside mt-1">
            {claim.sources.map((source, idx) => (
              <li key={idx} className="text-blue-600 hover:underline">
                {source.includes("http") ? (
                  <a href={source} target="_blank" rel="noopener noreferrer">
                    {source}
                  </a>
                ) : (
                  source
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

function App() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("checker");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!youtubeUrl.trim()) return setError("Please enter a YouTube URL");
    setLoading(true); setError(""); setResult(null);

    try {
      const response = await axios.post(`${API}/fact-check/youtube`, { url: youtubeUrl.trim() });
      setResult(response.data);
    } catch (error) {
      setError(error.response?.data?.detail || "An error occurred while processing the video");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <div className="container mx-auto px-4 py-8">
        <div className="flex space-x-4 mb-8">
          <button
            onClick={() => setActiveTab('checker')}
            className={`px-6 py-3 rounded-lg font-medium transition-colors ${
              activeTab === 'checker'
                ? 'bg-blue-600 text-white'
                : 'bg-white text-gray-700 hover:bg-blue-50'
            }`}
          >
            🎯 Fact Checker
          </button>
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-6 py-3 rounded-lg font-medium transition-colors ${
              activeTab === 'dashboard'
                ? 'bg-blue-600 text-white'
                : 'bg-white text-gray-700 hover:bg-blue-50'
            }`}
          >
            📊 Dashboard
          </button>
        </div>

        {activeTab === 'checker' && (
          <>
          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="url"
              value={youtubeUrl}
              onChange={(e) => setYoutubeUrl(e.target.value)}
              placeholder="YouTube URL"
              className="w-full border px-4 py-2 rounded"
              disabled={loading}
            />
              <button type="submit" disabled={loading} className="px-6 py-2 bg-blue-600 text-white rounded">
                {loading ? "Analyzing..." : "Analyze Video"}
              </button>
          </form>

            {result && <StatsSummary result={result} />}


            {result && result.claims.map((claim, idx) => (
              <ClaimCard key={idx} claim={claim} />
            ))}
          </>
        )}

        {activeTab === 'dashboard'}
      </div>
    </div>
  );
}

export default App;