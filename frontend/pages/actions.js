import React from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import ActionsPanel from '../components/ActionsPanel';

export default function Actions() {
  return (
    <Layout>
      <Head>
        <title>Actions - Xauto</title>
      </Head>
      <ActionsPanel />
    </Layout>
  );
}
