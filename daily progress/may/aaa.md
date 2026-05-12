cd terraform
terraform apply

terraform destroy

# bastion
ssh -A -i ~/.ssh/ameyaDB ec2-user@<bastion_ip>

# ec2
ssh -i ~/.ssh/ameyaDB ec2-user@node-0.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-1.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-2.ameyadb.internal

# run
chmod +x deploy
./deploy

# delete
rm ~/ameyaDB/terraform/terraform.tfstate.*.backup

never delete
* terraform.tfstate
* terraform.tfstate.backup
