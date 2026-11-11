import React, { useState, useEffect } from 'react';

interface TypewriterTextProps {
  text: string;
  speed?: number;
  onComplete?: () => void;
  className?: string;
}

export const TypewriterText: React.FC<TypewriterTextProps> = ({
  text,
  speed = 28,
  onComplete,
  className = '',
}) => {
  const [displayedText, setDisplayedText] = useState('');
  const [isDone, setIsDone] = useState(false);

  useEffect(() => {
    let index = 0;
    setDisplayedText('');
    setIsDone(false);

    const interval = setInterval(() => {
      index++;
      if (index <= text.length) {
        setDisplayedText(text.slice(0, index));
      } else {
        clearInterval(interval);
        setIsDone(true);
        if (onComplete) onComplete();
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, speed]);

  const handleSkip = () => {
    setDisplayedText(text);
    setIsDone(true);
    if (onComplete) onComplete();
  };

  return (
    <div onClick={handleSkip} className={`cursor-pointer ${className}`} title="Кликните, чтобы показать весь текст">
      <span>{displayedText}</span>
      {!isDone && (
        <span className="inline-block w-2.5 h-5 ml-1 bg-indigo-400 animate-pulse translate-y-0.5" />
      )}
    </div>
  );
};
