
bastion ip = 3.208.105.12

cd terraform
terraform apply

cd terraform
terraform destroy

# bastion
ssh -i ~/.ssh/ameyaDB ec2-user@3.208.105.12

# ec2
ssh -i ~/.ssh/ameyaDB ec2-user@node-0.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-1.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-2.ameyadb.internal









