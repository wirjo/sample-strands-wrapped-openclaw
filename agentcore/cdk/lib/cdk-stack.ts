import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  AgentCoreApplication,
  type HarnessDeploymentConfig,
} from '@aws/agentcore-cdk';
import type { AgentCoreProjectSpec } from '@aws/agentcore-cdk';

export interface HarnessConfig extends HarnessDeploymentConfig {}

export interface AgentCoreStackProps extends cdk.StackProps {
  spec: AgentCoreProjectSpec;
  mcpSpec?: unknown;
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
  connectorParametersByFile?: Record<string, Record<string, unknown>>;
  harnesses?: HarnessConfig[];
  paymentSpec?: unknown;
}

export class AgentCoreStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    new AgentCoreApplication(this, 'Application', {
      spec: props.spec,
      harnesses: props.harnesses,
      connectorParametersByFile: props.connectorParametersByFile,
      credentials: props.credentials,
    });
  }
}
