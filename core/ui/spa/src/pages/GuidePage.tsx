import React from 'react';
import './GuidePage.css';

interface GuidePageProps {
  title: string;
  content: React.ReactNode;
}

const GuidePage: React.FC<GuidePageProps> = ({ title, content }) => {
  return (
    <div className="guide-container">
      <h1>{title}</h1>
      {content}
    </div>
  );
};

export default GuidePage;
