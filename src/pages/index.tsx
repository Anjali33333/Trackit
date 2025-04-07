import { useState } from 'react';
import { motion } from 'framer-motion';
import Head from 'next/head';
import LoginForm from '../components/LoginForm';
import SignupForm from '../components/SignupForm';

export default function Home() {
  const [showLogin, setShowLogin] = useState(true);

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-100 to-secondary-100">
      <Head>
        <title>TRACKIT - Attendance Management System</title>
        <meta name="description" content="Modern attendance tracking system for educational institutions" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main className="container mx-auto px-4 py-8">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <h1 className="text-5xl font-bold text-primary-800 mb-4">
            Welcome to TRACKIT
          </h1>
          <p className="text-xl text-gray-600">
            Your Modern Attendance Management Solution
          </p>
        </motion.div>

        <div className="max-w-md mx-auto">
          <div className="bg-white rounded-lg shadow-xl overflow-hidden">
            <div className="flex border-b border-gray-200">
              <button
                className={`flex-1 py-4 text-sm font-medium text-center ${
                  showLogin
                    ? 'text-primary-600 border-b-2 border-primary-500'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
                onClick={() => setShowLogin(true)}
              >
                Login
              </button>
              <button
                className={`flex-1 py-4 text-sm font-medium text-center ${
                  !showLogin
                    ? 'text-primary-600 border-b-2 border-primary-500'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
                onClick={() => setShowLogin(false)}
              >
                Sign Up
              </button>
            </div>

            <motion.div
              key={showLogin ? 'login' : 'signup'}
              initial={{ opacity: 0, x: showLogin ? -20 : 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: showLogin ? 20 : -20 }}
              transition={{ duration: 0.3 }}
              className="p-6"
            >
              {showLogin ? <LoginForm /> : <SignupForm />}
            </motion.div>
          </div>
        </div>
      </main>

      {/* Animated background elements */}
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <motion.div
          animate={{
            scale: [1, 1.2, 1],
            rotate: [0, 180, 360],
          }}
          transition={{
            duration: 20,
            repeat: Infinity,
            repeatType: "reverse",
          }}
          className="absolute -top-1/2 -left-1/2 w-full h-full bg-gradient-to-r from-primary-200/20 to-secondary-200/20 rounded-full"
        />
        <motion.div
          animate={{
            scale: [1.2, 1, 1.2],
            rotate: [360, 180, 0],
          }}
          transition={{
            duration: 20,
            repeat: Infinity,
            repeatType: "reverse",
          }}
          className="absolute -bottom-1/2 -right-1/2 w-full h-full bg-gradient-to-l from-primary-200/20 to-secondary-200/20 rounded-full"
        />
      </div>
    </div>
  );
} 