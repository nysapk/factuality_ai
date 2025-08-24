import React from "react";
import "./App.css";

const Header = () => (
  <header className="bg-gradient-to-r from-blue-600 to-purple-700 text-white py-6 px-4 shadow-lg">
    <div className="container mx-auto">
      <h1 className="text-3xl font-bold mb-2">🎯 Factuality</h1>
      <p className="text-blue-100">Real-time Fact Checker for YouTube Videos</p>
    </div>
  </header>
);

function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <div className="container mx-auto px-4 py-8">
        <p className="text-gray-600">Welcome to Factuality!</p>
      </div>
    </div>
  );
}

export default App;
